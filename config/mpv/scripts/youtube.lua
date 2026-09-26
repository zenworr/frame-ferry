local msg = require("mp.msg")
local numeric_options = {
    recovery_timeout = { default = 30, minimum = 10, maximum = 300 },
    stall_timeout = { default = 10, minimum = 3, maximum = 120 },
    http_chunk_size = { default = 1024 * 1024, minimum = 0, maximum = 8 * 1024 * 1024 },
}
local options = { cookies_browser = "", cookies_initial = false, auto_update = false }
for name, policy in pairs(numeric_options) do
    options[name] = policy.default
end
require("mp.options").read_options(options, "youtube")
for name, policy in pairs(numeric_options) do
    local value = tonumber(options[name])
    if not value or value ~= value or value < policy.minimum or value > policy.maximum then
        msg.warn("Invalid " .. name .. "; using its default")
        value = policy.default
    end
    options[name] = value
end
local MIN_HTTP_CHUNK_SIZE = 64 * 1024
if
    options.http_chunk_size ~= 0
    and (options.http_chunk_size < MIN_HTTP_CHUNK_SIZE or options.http_chunk_size % 1 ~= 0)
then
    options.http_chunk_size = numeric_options.http_chunk_size.default
end
local recovery_timeout = options.recovery_timeout
local timeout_scale = recovery_timeout / numeric_options.recovery_timeout.default
local PLAYBACK_POLL_INTERVAL = 1
local SYNC_TOLERANCE = 1
local END_MARGIN = 1
local MIN_FULL_QUALITY_BUDGET = 10
local MIN_EXTRACTION_TIMEOUT = 0.1
local EXTRACTION_MARGIN = 0.5
local MIN_CHUNKED_FFMPEG = 9
local HOOK = { prepare = 5, retain = 15, transport = 20, recover = 40 }
local VIDEO_WIDTH = { uhd = 3840, uhd8k = 7680 }
local OSD_SECONDS = { short = 2, long = 4 }
local SLATE = {
    width = 1280,
    height = 720,
    title_y = 320,
    title_font = 36,
    controls_font = 23,
    detail_font = 19,
    color = "0x10131a",
}

local next_mode, mode, youtube_url, failed, unsupported, pause_before_error
local timer, playback_timer, stall_started, stall_reason, last_reader, live_stream, timed_out, started, loaded
local use_cookies, requires_auth, last_position, resume_position
local showing_slate, announced_size, playlist_entry, selected_format, candidate_path, candidate_file
local slate = mp.create_osd_overlay("ass-events")
local marker = "YouTube post-live DASH fragments lack reliable timing"
local routes = {
    primary = { next = "authenticated", budget = 6, label = "Direct", notice = "Trying selected quality" },
    authenticated = {
        next = "token",
        budget = 8,
        label = "Signed in",
        notice = "Trying selected quality with browser sign-in",
    },
    token = {
        next = "hls",
        budget = 8,
        label = "Token-assisted",
        notice = "Trying selected quality with a playback token",
    },
    hls = { next = "fallback", budget = 7, label = "HLS", notice = "Trying selected quality over HLS" },
    retained = {
        next = "fallback",
        budget = 7,
        label = "Earlier stream",
        notice = "Trying the earlier stream without another extraction",
    },
    fallback = { next = "error", budget = 7, label = "Fast fallback", notice = "Trying fast fallback (maximum 1080p)" },
}

local function is_youtube(url)
    local host = (url or ""):lower():match("^https?://([^/?#]+)")
    if not host then
        return false
    end
    host = host:gsub("^.*@", ""):gsub(":%d+$", ""):gsub("%.$", "")
    return host == "youtu.be"
        or host == "youtube.com"
        or host == "youtube-nocookie.com"
        or host:match("%.youtube%.com$")
        or host:match("%.youtube%-nocookie%.com$")
end

local function cancel_timer()
    if timer then
        timer:kill()
        timer = nil
    end
end

local function cancel_playback_timer()
    if playback_timer then
        playback_timer:kill()
    end
    stall_started, stall_reason, last_reader = nil, nil, nil
end

local function abort_load(target)
    if not youtube_url or (target ~= "primary" and showing_slate) then
        return
    end
    cancel_timer()
    cancel_playback_timer()
    next_mode, timed_out = target, true
    mp.commandv("stop", "keep-playlist")
end

local function can_recover_playback()
    return youtube_url
        and loaded
        and not showing_slate
        and not live_stream
        and mp.get_property_bool("demuxer-via-network", false)
        and mp.get_property_number("duration", 0) > 0
        and not mp.get_property_bool("pause", false)
        and not mp.get_property_bool("seeking", false)
        and not mp.get_property_bool("eof-reached", false)
end

local function check_playback()
    if not can_recover_playback() then
        cancel_playback_timer()
        return
    end
    local reason
    if mp.get_property_bool("paused-for-cache", false) then
        reason = "Playback stalled while buffering."
    elseif
        mp.get_property_number("current-tracks/video/id")
        and not mp.get_property_bool("current-tracks/video/image", false)
    then
        local audio = mp.get_property_number("audio-pts")
        local cache = mp.get_property_native("demuxer-cache-state", {})
        local reader
        for _, stream in ipairs(cache["ts-per-stream"] or {}) do
            if stream.type == "video" then
                reader = stream["reader-pts"]
                break
            end
        end
        if reader ~= last_reader then
            stall_started, stall_reason = nil, nil
        end
        last_reader = reader
        -- A failed video demuxer can leave audio playing without a cache pause or end-file event.
        if
            audio
            and type(reader) == "number"
            and audio > reader + SYNC_TOLERANCE
            and audio < mp.get_property_number("duration", 0) - END_MARGIN
        then
            reason = "Video stream stopped while audio continued."
        end
    end
    if not reason then
        stall_started, stall_reason = nil, nil
    elseif reason ~= stall_reason then
        stall_started, stall_reason = mp.get_time(), reason
    elseif mp.get_time() - stall_started >= options.stall_timeout then
        msg.warn(reason .. " Trying the next recovery route")
        mp.set_property("user-data/youtube-quality/error", reason)
        -- Advance through the existing bounded ladder, never retry one broken route forever.
        abort_load(nil)
    end
end

playback_timer = mp.add_periodic_timer(PLAYBACK_POLL_INTERVAL, check_playback)
playback_timer:kill()
local function watch_playback()
    if can_recover_playback() then
        playback_timer:resume()
        check_playback()
    else
        cancel_playback_timer()
    end
end
for _, property in ipairs({ "paused-for-cache", "pause", "seeking", "eof-reached" }) do
    mp.observe_property(property, "bool", watch_playback)
end

local function clear_candidate()
    if candidate_file then
        candidate_file:close()
    end
    candidate_path, candidate_file = nil, nil
end
mp.register_event("shutdown", clear_candidate)

mp.add_hook("on_load", HOOK.prepare, function()
    cancel_timer()
    cancel_playback_timer()
    live_stream = false
    slate:remove()
    local path = mp.get_property("path", "")
    local entry = mp.get_property(string.format("playlist/%d/id", mp.get_property_number("playlist-pos", 0)))
    local format = mp.get_property("ytdl-format")
    if path ~= youtube_url or entry ~= playlist_entry or format ~= selected_format then
        next_mode = nil
    end
    playlist_entry, selected_format = entry, format
    mode = next_mode or "primary"
    if not next_mode then
        resume_position = nil
        -- Explicit URL time takes precedence over watch history, including fractional handoff positions.
        local query = is_youtube(path) and path:match("%?([^#]*)") or ""
        for part in query:gmatch("[^&]+") do
            local position = tonumber(part:match("^t=(%d+%.?%d*)$"))
            if position and position < math.huge then
                resume_position = position
                break
            end
        end
    end
    if not next_mode or mode == "primary" then
        started, use_cookies, requires_auth = mp.get_time(), false, false
        clear_candidate()
    end
    if mode ~= "error" and mode ~= "browser" and pause_before_error ~= nil then
        mp.set_property_bool("pause", pause_before_error)
        pause_before_error = nil
    end
    next_mode, failed, unsupported, timed_out, loaded, last_position = nil, false, false, false, false, nil
    showing_slate, announced_size = false, nil
    youtube_url = is_youtube(path) and path or nil
    mp.set_property("user-data/youtube-quality/badge", "")
    mp.set_property_bool("user-data/youtube-quality/active", youtube_url ~= nil)
    mp.set_property_bool("user-data/youtube-quality/loading", false)
    mp.set_property_bool("user-data/youtube-quality/slate", false)
    mp.set_property("user-data/youtube-quality/route", "")
    if not youtube_url then
        return
    end

    local remaining = recovery_timeout - (mp.get_time() - started)
    if mode ~= "browser" then
        if remaining <= 0 then
            mode = "error"
        elseif mode ~= "error" and mode ~= "fallback" and remaining < MIN_FULL_QUALITY_BUDGET * timeout_scale then
            mode = "fallback"
        end
    end
    if mode == "fallback" and candidate_path then
        mode = "retained"
    end
    mp.set_property("user-data/youtube-quality/route", mode)
    showing_slate = mode == "error" or mode == "browser"
    mp.set_property_bool("user-data/youtube-quality/slate", showing_slate)
    if showing_slate then
        clear_candidate()
        pause_before_error = mp.get_property_bool("pause", false)
        -- A lavfi URL bypasses extraction without unloading ytdl_hook.
        mp.set_property(
            "stream-open-filename",
            string.format("av://lavfi:color=c=%s:s=%dx%d:r=1", SLATE.color, SLATE.width, SLATE.height)
        )
        mp.set_property(
            "file-local-options/force-media-title",
            mode == "browser" and "Continue in browser" or "YouTube playback failed"
        )
        mp.set_property_bool("pause", true)
        return
    end

    mp.set_property("user-data/youtube-quality/error", "")
    -- Reserve time for a usable fallback, including a short availability wait.
    local budget = math.min(
        routes[mode].budget * timeout_scale,
        remaining - ((mode == "fallback" or mode == "retained") and 0 or routes.fallback.budget * timeout_scale)
    )
    local raw = mp.get_property_native("options/ytdl-raw-options", {})
    if mode == "hls" or mode == "fallback" then
        use_cookies = requires_auth
    end
    use_cookies = use_cookies or mode == "authenticated" or raw["cookies-from-browser"] ~= nil or raw.cookies ~= nil
    use_cookies = use_cookies or (options.cookies_initial and options.cookies_browser ~= "")
    if use_cookies and options.cookies_browser ~= "" and not raw["cookies-from-browser"] and not raw.cookies then
        raw["cookies-from-browser"] = options.cookies_browser
    end
    raw["frameferry-update"] = options.auto_update and "yes" or "no"
    raw["frameferry-route"] = mode
    raw["frameferry-candidate"] = mode == "retained" and candidate_path or nil
    raw["frameferry-timeout"] = tostring(math.max(MIN_EXTRACTION_TIMEOUT, budget - EXTRACTION_MARGIN * timeout_scale))
    mp.set_property_native("file-local-options/ytdl-raw-options", raw)
    if resume_position then
        mp.set_property("file-local-options/start", tostring(resume_position))
    end
    mp.set_property_bool("user-data/youtube-quality/loading", true)
    msg.info(routes[mode].notice)
    mp.osd_message(routes[mode].notice .. "\nAlt+q: fast fallback    Ctrl+b: browser", budget)
    -- Bound extraction and media opening, including HLS segment retry loops.
    timer = mp.add_timeout(budget, function()
        mp.set_property("user-data/youtube-quality/error", "Loading exceeded the recovery time limit.")
        abort_load(routes[mode].next)
    end)
end)

mp.add_hook("on_load", HOOK.retain, function()
    local result = mp.get_property_native("user-data/mpv/ytdl/json-subprocess-result")
    if
        not youtube_url
        or showing_slate
        or candidate_path
        or type(result) ~= "table"
        or result.status ~= 1
        or type(result.stdout) ~= "string"
        or result.stdout == ""
        or not (result.stderr or ""):find("yt-dlp-mpv: limited authenticated formats; try token route", 1, true)
    then
        return
    end
    -- Unlink before writing signed URLs; even SIGKILL then leaves no named metadata file.
    local ok, path = pcall(os.tmpname)
    local file = ok and io.open(path, "w+")
    local removed = ok and os.remove(path)
    if file and removed then
        local written = file:write(result.stdout)
        local flushed = file:flush()
        if written and flushed then
            candidate_path, candidate_file = path, file
        else
            file:close()
        end
    elseif file then
        file:close()
    end
    if not candidate_path then
        msg.warn("Could not retain the earlier stream")
    end
    mp.set_property("stream-open-filename", "memory://")
end)

mp.add_hook("on_load", HOOK.transport, function()
    if not youtube_url or showing_slate then
        return
    end
    local result = mp.get_property_native("user-data/mpv/ytdl/json-subprocess-result")
    if type(result) ~= "table" or result.status ~= 0 or type(result.stdout) ~= "string" then
        return
    end
    local info = require("mp.utils").parse_json(result.stdout)
    if type(info) ~= "table" then
        return
    end
    live_stream = info.is_live
        or info.live_status == "is_live"
        or info.live_status == "post_live"
        or info.live_status == "is_upcoming"
    if live_stream then
        return
    end
    -- Bounded HTTP requests require FFmpeg 9 or newer.
    local version = tonumber(mp.get_property("ffmpeg-version", ""):match("^n?(%d+)%.")) or 0
    if version < MIN_CHUNKED_FFMPEG or options.http_chunk_size == 0 then
        return
    end
    local formats = info.requested_formats or info.requested_downloads or { info }
    if #formats == 0 then
        return
    end
    for _, format in ipairs(formats) do
        if
            (format.protocol ~= "http" and format.protocol ~= "https")
            or format.fragments
            or type(format.url) ~= "string"
            or not format.url:match("^https?://")
        then
            return
        end
    end
    -- yt-dlp's downloader chunk size does not carry over to mpv's media reader.
    local stream = mp.get_property_native("file-local-options/stream-lavf-o", {})
    local chunk = tostring(options.http_chunk_size)
    for key, value in pairs({ request_size = chunk, multiple_requests = "1", short_seek_size = chunk }) do
        if stream[key] == nil then
            stream[key] = value
        end
    end
    mp.set_property_native("file-local-options/stream-lavf-o", stream)
end)

mp.observe_property("user-data/mpv/ytdl/json-subprocess-result", "native", function(_, result)
    if type(result) == "table" and type(result.stderr) == "string" then
        unsupported = result.stderr:find(marker, 1, true) ~= nil
        local err = result.stderr:lower()
        requires_auth = requires_auth
            or err:find("sign in", 1, true) ~= nil
            or err:find("log in", 1, true) ~= nil
            or err:find("members-only", 1, true) ~= nil
            or err:find("private video", 1, true) ~= nil
        if result.status ~= 0 then
            local reason
            if err:find("http error 429", 1, true) or err:find("too many requests", 1, true) then
                reason = "YouTube is limiting requests. Wait before trying again."
            elseif
                err:find("sign in", 1, true)
                or err:find("log in", 1, true)
                or err:find("members-only", 1, true)
                or err:find("private video", 1, true)
            then
                reason = "YouTube requested account access. Check browser-cookie settings or continue in the browser."
            elseif err:find("extraction timed out", 1, true) then
                reason = "YouTube extraction timed out."
            elseif err:find("requested format is not available", 1, true) then
                reason = "The requested video format is unavailable."
            end
            if reason then
                mp.set_property("user-data/youtube-quality/error", reason)
            end
        end
    end
end)

mp.observe_property("time-pos", "number", function(_, value)
    if youtube_url and not showing_slate and value then
        last_position = value
    end
end)

local function show_quality(_, video)
    if showing_slate or not video or not video.w or not video.h then
        return
    end
    local badge = video.w >= VIDEO_WIDTH.uhd8k and "8K" or video.w >= VIDEO_WIDTH.uhd and "4K" or (video.h .. "p")
    mp.set_property("user-data/youtube-quality/badge", badge)
    local size = string.format("%dx%d", video.w, video.h)
    if youtube_url and loaded and size ~= announced_size then
        announced_size = size
        mp.osd_message(
            size .. " | " .. routes[mode].label .. "\nF2: quality",
            mode == "primary" and OSD_SECONDS.short or OSD_SECONDS.long
        )
    end
end
mp.observe_property("video-params", "native", show_quality)

mp.register_event("end-file", function(event)
    cancel_timer()
    cancel_playback_timer()
    mp.set_property_bool("user-data/youtube-quality/loading", false)
    failed = youtube_url ~= nil
        and event.reason ~= "quit"
        and ((event.reason == "error" and not showing_slate) or timed_out)
    if mode == "retained" then
        clear_candidate()
    end
    if failed and loaded and not showing_slate then
        started = mp.get_time()
        if not mp.get_property_bool("demuxer-via-network", false) or mp.get_property_number("duration", 0) > 0 then
            resume_position = last_position or resume_position
        end
    end
    loaded = false
end)

-- This hook runs before mpv chooses its next file or exits.
mp.add_hook("on_after_end_file", HOOK.recover, function()
    if not failed then
        return
    end
    failed = false
    if not next_mode then
        next_mode = routes[mode].next
        if unsupported and mode ~= "hls" and mode ~= "fallback" then
            next_mode = "hls"
        end
        if mode == "primary" and (use_cookies or options.cookies_browser == "") and next_mode == "authenticated" then
            next_mode = "token"
        end
    end
    if next_mode ~= "browser" and mp.get_time() - started >= recovery_timeout then
        next_mode = "error"
    end
    if next_mode == "error" then
        msg.error("YouTube playback routes failed or exceeded the time limit")
    end
    mp.commandv("playlist-play-index", "current")
end)

mp.register_event("file-loaded", function()
    cancel_timer()
    clear_candidate()
    loaded = true
    watch_playback()
    mp.set_property_bool("user-data/youtube-quality/loading", false)
    if not youtube_url then
        return
    end
    mp.osd_message("")
    if not showing_slate then
        show_quality(nil, mp.get_property_native("video-params", {}))
        return
    end
    mp.set_property_bool("pause", true)
    slate.res_x, slate.res_y = SLATE.width, SLATE.height
    local title = mode == "browser" and "Continue in browser" or "YouTube playback failed"
    local detail = mp.get_property("user-data/youtube-quality/error", "")
    if mode == "browser" then
        detail = "Loading stopped. Press Ctrl+r to return to mpv."
    elseif detail == "" then
        detail = "No usable stream within the load budget."
    end
    slate.data = string.format(
        "{\\an5\\pos(%d,%d)\\fs%d\\bord1}%s\\N{\\fs%d}Ctrl+r: retry    Ctrl+b: open in browser\\N{\\fs%d}%s",
        SLATE.width / 2,
        SLATE.title_y,
        SLATE.title_font,
        title,
        SLATE.controls_font,
        SLATE.detail_font,
        detail
    )
    slate:update()
end)

mp.add_key_binding("Alt+q", "youtube-fast-fallback", function()
    abort_load("fallback")
end)
mp.add_key_binding("Ctrl+r", "youtube-retry", function()
    if youtube_url then
        started = mp.get_time()
        abort_load("primary")
    end
end)

mp.add_key_binding("Ctrl+b", "youtube-browser", function()
    if youtube_url then
        local url = youtube_url
        local position = (not showing_slate and mp.get_property_number("time-pos")) or last_position or resume_position
        if position and position >= 0 and (resume_position or mp.get_property_number("duration", 0) > 0) then
            local base, query = url:match("^([^#?]+)%??([^#]*)")
            local params = {}
            for part in query:gmatch("[^&]+") do
                if not part:match("^t=") and not part:match("^start=") and not part:match("^time_continue=") then
                    params[#params + 1] = part
                end
            end
            params[#params + 1] = "t=" .. math.floor(position)
            url = base .. "?" .. table.concat(params, "&")
        end
        if loaded then
            mp.set_property_bool("pause", true)
        else
            abort_load("browser")
        end
        mp.command_native_async(
            { name = "subprocess", playback_only = false, args = { "xdg-open", url } },
            function(success, result)
                if success and result and result.status == 0 then
                    mp.commandv("quit")
                else
                    mp.osd_message("Could not open the browser", OSD_SECONDS.long)
                end
            end
        )
    end
end)
