local mock = dofile("tests/mp_mock.lua")
local function player(info, path, cookies, timeout)
    local p = mock("config/mpv/scripts/youtube.lua", {
        options = { cookies_browser = cookies or "chromium:test", stall_timeout = timeout },
        utils = {
            parse_json = function()
                return info or {}
            end,
        },
    })
    p.properties.path = path or "https://www.youtube.com/watch?v=fixture"
    p.properties.duration = 180
    p.properties["demuxer-via-network"] = true
    p.watchdog = p.timers[1]
    assert(p.watchdog.seconds == 1)
    function p.load()
        p.properties["file-local-options/start"] = nil
        p.hook("on_load", 5)
        p.properties["user-data/mpv/ytdl/json-subprocess-result"] = { status = 0, stdout = "metadata" }
        p.hook("on_load", 20)
        p.fire("file-loaded")
    end
    function p.tick(seconds)
        for _ = 1, seconds do
            p.clock = p.clock + 1
            if not p.watchdog.killed then
                p.watchdog.fn()
            end
        end
    end
    function p.buffer()
        p.observe("paused-for-cache", true)
    end
    function p.recover()
        p.fire("end-file", { reason = "stop" })
        p.hook("on_after_end_file")
        p.properties["paused-for-cache"] = false
        p.load()
    end
    p.load()
    return p
end

for _, case in ipairs({ { 3, 3 }, { 20, 20 }, { 0, 10 }, { math.huge, 10 } }) do
    local configured = player(nil, nil, nil, case[1])
    configured.buffer()
    configured.tick(case[2] - 1)
    assert(#configured.commands == 0)
    configured.tick(1)
    assert(#configured.commands == 1, "stall timeout was not applied or safely validated")
end
local p = player()
for _, route in ipairs({ "authenticated", "token", "hls", "fallback", "error" }) do
    p.observe("time-pos", 42)
    p.buffer()
    p.tick(5)
    p.buffer()
    local count = #p.commands
    p.tick(4)
    assert(#p.commands == count, "recovery triggered before ten seconds")
    p.tick(1)
    assert(#p.commands == count + 1, "duplicate notifications reset the stall deadline")
    assert(p.commands[#p.commands][1] == "stop")
    p.recover()
    assert(p.properties["user-data/youtube-quality/route"] == route, "recovery repeated or skipped a route")
    if route ~= "error" then
        assert(p.properties["file-local-options/start"] == "42")
    end
end
assert(p.properties["user-data/youtube-quality/slate"], "fallback buffering caused an endless retry loop")
assert(p.overlay.data:find("Playback stalled while buffering.", 1, true))
assert(p.watchdog.killed)

for _, property in ipairs({ "pause", "seeking", "paused-for-cache", "eof-reached" }) do
    local q = player()
    q.buffer()
    q.tick(5)
    q.observe(property, property ~= "paused-for-cache")
    q.tick(10)
    assert(#q.commands == 0, "pause, seek, end, or resumed playback did not cancel recovery")
    q.observe(property, property == "paused-for-cache")
    q.tick(9)
    assert(#q.commands == 0)
    q.tick(1)
    assert(#q.commands == 1)
end
for _, info in ipairs({
    { is_live = true },
    { live_status = "is_live" },
    { live_status = "post_live" },
    { live_status = "is_upcoming" },
}) do
    local q = player(info)
    q.buffer()
    q.tick(20)
    assert(q.watchdog.killed, "live stream started recorded-video recovery")
end
for _, path in ipairs({ "/tmp/video.mp4", "https://example.org/video" }) do
    local q = player(nil, path)
    q.buffer()
    q.tick(20)
    assert(q.watchdog.killed, "unrelated media started YouTube recovery")
end
local q = player()
q.buffer()
q.fire("end-file", { reason = "stop" })
q.observe("paused-for-cache", true)
assert(q.watchdog.killed, "unloaded file restarted recovery")
q = player(nil, nil, "")
q.buffer()
q.tick(10)
q.recover()
assert(q.properties["user-data/youtube-quality/route"] == "token", "automatic recovery tried unconfigured cookies")
q = player()
q.observe("time-pos", 65)
q.keys["Alt+q"]()
q.recover()
assert(q.properties["user-data/youtube-quality/route"] == "fallback")
assert(q.properties["file-local-options/start"] == "65")

local function video_cache(position)
    return { ["ts-per-stream"] = { { type = "video", ["reader-pts"] = position } } }
end
local function frozen_video()
    local r = player()
    r.properties["current-tracks/video/id"] = 1
    r.properties["audio-pts"] = 60
    r.properties["demuxer-cache-state"] = video_cache(40)
    r.observe("time-pos", 60)
    r.observe("paused-for-cache", false)
    return r
end
q = frozen_video()
q.tick(10)
assert(#q.commands == 1, "audio-only progress hid a failed video stream")
q.recover()
assert(q.properties["user-data/youtube-quality/route"] == "authenticated")
assert(q.properties["file-local-options/start"] == "60")
for _, case in ipairs({
    { "current-tracks/video/id", false },
    { "current-tracks/video/image", true },
    { "audio-pts", 179.5 },
    { "pause", true },
    { "seeking", true },
    { "demuxer-cache-state", {} },
    { "demuxer-cache-state", video_cache(60) },
    { "demuxer-cache-state", { ["reader-pts"] = 40 } },
}) do
    q = frozen_video()
    q.observe(case[1], case[2])
    q.tick(20)
    assert(#q.commands == 0, "normal playback or user input triggered false recovery: " .. case[1])
end
for _, offset in ipairs({ 1, -5 }) do
    q = frozen_video()
    for position = 60, 80 do
        q.properties["audio-pts"] = position
        q.properties["demuxer-cache-state"] = video_cache(position + offset)
        q.tick(1)
    end
    assert(#q.commands == 0, "moving video caused false recovery")
end
for _, case in ipairs({
    { "ERROR: Sign in to confirm you are not a bot https://private.test/token", "account access" },
    { "ERROR: HTTP Error 429: Too Many Requests https://private.test/token", "limiting requests" },
    { "yt-dlp-mpv: extraction timed out", "timed out" },
    { "ERROR: Requested format is not available", "format is unavailable" },
}) do
    local r = player()
    r.observe("user-data/mpv/ytdl/json-subprocess-result", { status = 1, stderr = case[1] })
    local error = r.properties["user-data/youtube-quality/error"]
    assert(error:find(case[2], 1, true))
    assert(not error:find("private", 1, true), "failure reason exposed provider URLs")
end
print("Playback recovery: buffer stalls, partial video failure, cancellation, scope, and safe errors passed")
