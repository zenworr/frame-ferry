local msg = require("mp.msg")
local options = {cookies_browser = "", cookies_initial = false, auto_update = false}
require("mp.options").read_options(options, "youtube")

local next_mode, mode, youtube_url, failed, unsupported, pause_before_error
local timer, timed_out, started, loaded, use_cookies, requires_auth, last_position, resume_position
local showing_slate, announced_size, playlist_entry, selected_format, candidate_path, candidate_file
local slate = mp.create_osd_overlay("ass-events")
local marker = "YouTube post-live DASH fragments lack reliable timing"
local following = {primary = "authenticated", authenticated = "token", token = "hls", hls = "fallback",
    retained = "fallback", fallback = "error"}
local budgets = {primary = 6, authenticated = 8, token = 8, hls = 7, retained = 7, fallback = 7}
local notices = {
    primary = "Trying selected quality",
    authenticated = "Trying selected quality with browser sign-in",
    token = "Trying selected quality with a playback token",
    hls = "Trying selected quality over HLS",
    retained = "Trying the earlier stream without another extraction",
    fallback = "Trying fast fallback (maximum 1080p)",
}
local route_names = {primary = "Direct", authenticated = "Signed in", token = "Token-assisted",
    hls = "HLS", retained = "Earlier stream", fallback = "Fast fallback"}

local function is_youtube(url)
    local host = (url or ""):lower():match("^https?://([^/?#]+)")
    if not host then return false end
    host = host:gsub("^.*@", ""):gsub(":%d+$", ""):gsub("%.$", "")
    return host == "youtu.be" or host == "youtube.com" or host == "youtube-nocookie.com"
        or host:match("%.youtube%.com$") or host:match("%.youtube%-nocookie%.com$")
end

local function cancel_timer()
    if timer then timer:kill(); timer = nil end
end

local function abort_load(target)
    if not youtube_url or (target ~= "primary" and (loaded or showing_slate)) then return end
    cancel_timer()
    next_mode, timed_out = target, true
    mp.commandv("stop", "keep-playlist")
end

local function clear_candidate()
    if candidate_file then candidate_file:close() end
    candidate_path, candidate_file = nil, nil
end
mp.register_event("shutdown", clear_candidate)

mp.add_hook("on_load", 5, function()
    cancel_timer()
    slate:remove()
    local path = mp.get_property("path", "")
    local entry = mp.get_property(string.format("playlist/%d/id", mp.get_property_number("playlist-pos", 0)))
    local format = mp.get_property("ytdl-format")
    if path ~= youtube_url or entry ~= playlist_entry or format ~= selected_format then next_mode = nil end
    playlist_entry, selected_format = entry, format
    mode = next_mode or "primary"
    if not next_mode then
        resume_position = nil
        -- Browser handoff uses whole seconds; explicit URL time takes precedence over watch history.
        local query = is_youtube(path) and path:match("%?([^#]*)") or ""
        for part in query:gmatch("[^&]+") do
            local position = tonumber(part:match("^t=(%d+)$"))
            if position and position < math.huge then resume_position = position; break end
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
    if not youtube_url then return end

    local remaining = 30 - (mp.get_time() - started)
    if mode ~= "browser" then
        if remaining <= 0 then
            mode = "error"
        elseif mode ~= "error" and mode ~= "fallback" and remaining < 10 then
            mode = "fallback"
        end
    end
    if mode == "fallback" and candidate_path then mode = "retained" end
    mp.set_property("user-data/youtube-quality/route", mode)
    showing_slate = mode == "error" or mode == "browser"
    mp.set_property_bool("user-data/youtube-quality/slate", showing_slate)
    if showing_slate then
        clear_candidate()
        pause_before_error = mp.get_property_bool("pause", false)
        -- A lavfi URL bypasses extraction without unloading ytdl_hook.
        mp.set_property("stream-open-filename", "av://lavfi:color=c=0x10131a:s=1280x720:r=1")
        mp.set_property("file-local-options/force-media-title",
            mode == "browser" and "Continue in browser" or "YouTube playback failed")
        mp.set_property_bool("pause", true)
        return
    end

    -- Reserve time for a usable fallback, including a short availability wait.
    local budget = math.min(budgets[mode], remaining - ((mode == "fallback" or mode == "retained") and 0 or 7))
    local raw = mp.get_property_native("options/ytdl-raw-options", {})
    if mode == "hls" or mode == "fallback" then use_cookies = requires_auth end
    use_cookies = use_cookies or mode == "authenticated" or raw["cookies-from-browser"] ~= nil
        or raw.cookies ~= nil
    use_cookies = use_cookies or (options.cookies_initial and options.cookies_browser ~= "")
    if use_cookies and options.cookies_browser ~= "" and not raw["cookies-from-browser"] and not raw.cookies then
        raw["cookies-from-browser"] = options.cookies_browser
    end
    raw["frameferry-update"] = options.auto_update and "yes" or "no"
    raw["frameferry-route"] = mode
    raw["frameferry-candidate"] = mode == "retained" and candidate_path or nil
    raw["frameferry-timeout"] = tostring(math.max(0.1, budget - 0.5))
    mp.set_property_native("file-local-options/ytdl-raw-options", raw)
    mp.set_property_number("file-local-options/network-timeout", 4)
    if resume_position then mp.set_property("file-local-options/start", tostring(resume_position)) end
    mp.set_property_bool("user-data/youtube-quality/loading", true)
    msg.info(notices[mode])
    mp.osd_message(notices[mode] .. "\nAlt+q: fast fallback    Ctrl+b: browser", budget)
    -- Bound extraction and media opening, including HLS segment retry loops.
    timer = mp.add_timeout(budget, function() abort_load(following[mode]) end)
end)

mp.add_hook("on_load", 15, function()
    local result = mp.get_property_native("user-data/mpv/ytdl/json-subprocess-result")
    if not youtube_url or showing_slate or candidate_path or type(result) ~= "table"
        or result.status ~= 1 or type(result.stdout) ~= "string" or result.stdout == ""
        or not (result.stderr or ""):find("yt-dlp-mpv: limited authenticated formats; try token route", 1, true) then return end
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
    if not candidate_path then msg.warn("Could not retain the earlier stream") end
    mp.set_property("stream-open-filename", "memory://")
end)

mp.observe_property("user-data/mpv/ytdl/json-subprocess-result", "native", function(_, result)
    if type(result) == "table" and type(result.stderr) == "string" then
        unsupported = result.stderr:find(marker, 1, true) ~= nil
        local err = result.stderr:lower()
        requires_auth = requires_auth or err:find("sign in", 1, true) ~= nil
            or err:find("log in", 1, true) ~= nil or err:find("members-only", 1, true) ~= nil
            or err:find("private video", 1, true) ~= nil
    end
end)

mp.observe_property("time-pos", "number", function(_, value)
    if youtube_url and not showing_slate and value then last_position = value end
end)

local function show_quality(_, video)
    if showing_slate or not video or not video.w or not video.h then return end
    local badge = video.w >= 7680 and "8K" or video.w >= 3840 and "4K" or (video.h .. "p")
    mp.set_property("user-data/youtube-quality/badge", badge)
    local size = string.format("%dx%d", video.w, video.h)
    if youtube_url and loaded and size ~= announced_size then
        announced_size = size
        mp.osd_message(size .. " | " .. route_names[mode] .. "\nF2: quality", mode == "primary" and 2 or 4)
    end
end
mp.observe_property("video-params", "native", show_quality)

mp.register_event("end-file", function(event)
    cancel_timer()
    mp.set_property_bool("user-data/youtube-quality/loading", false)
    failed = youtube_url ~= nil and event.reason ~= "quit"
        and ((event.reason == "error" and not showing_slate) or timed_out)
    if mode == "retained" then clear_candidate() end
    if failed and loaded and not showing_slate then
        started = mp.get_time()
        if not mp.get_property_bool("demuxer-via-network", false) or mp.get_property_number("duration", 0) > 0 then
            resume_position = last_position or resume_position
        end
    end
end)

-- This hook runs before mpv chooses its next file or exits.
mp.add_hook("on_after_end_file", 40, function()
    if not failed then return end
    failed = false
    if not next_mode then
        next_mode = following[mode]
        if unsupported and mode ~= "hls" and mode ~= "fallback" then next_mode = "hls" end
        if mode == "primary" and (use_cookies or options.cookies_browser == "") and next_mode == "authenticated" then next_mode = "token" end
    end
    if next_mode ~= "browser" and mp.get_time() - started >= 30 then next_mode = "error" end
    if next_mode == "error" then msg.error("YouTube playback routes failed or exceeded the time limit") end
    mp.commandv("playlist-play-index", "current")
end)

mp.register_event("file-loaded", function()
    cancel_timer()
    clear_candidate()
    loaded = true
    mp.set_property_bool("user-data/youtube-quality/loading", false)
    if not youtube_url then return end
    mp.osd_message("")
    if not showing_slate then
        show_quality(nil, mp.get_property_native("video-params", {}))
        return
    end
    mp.set_property_bool("pause", true)
    slate.res_x, slate.res_y = 1280, 720
    local title = mode == "browser" and "Continue in browser" or "YouTube playback failed"
    local detail = mode == "browser" and "Loading stopped. Press Ctrl+r to return to mpv."
        or "No usable stream within the load budget."
    slate.data = "{\\an5\\pos(640,320)\\fs36\\bord1}" .. title ..
        "\\N{\\fs23}Ctrl+r: retry    Ctrl+b: open in browser" .. "\\N{\\fs19}" .. detail
    slate:update()
end)

mp.add_key_binding("Alt+q", "youtube-fast-fallback", function() abort_load("fallback") end)
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
        if loaded then mp.set_property_bool("pause", true) else abort_load("browser") end
        mp.command_native_async({name = "subprocess", playback_only = false,
            args = {"xdg-open", url}}, function(success, result)
                if not success or result.status ~= 0 then mp.osd_message("Could not open the browser", 4) end
            end)
    end
end)
