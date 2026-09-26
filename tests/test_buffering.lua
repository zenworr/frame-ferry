local mock = dofile("tests/mp_mock.lua")
local function player(info, path, cookies)
    local p = mock("config/mpv/scripts/youtube.lua", {
        options = {cookies_browser = cookies or "chromium:test"},
        utils = {parse_json = function() return info or {} end},
    })
    p.properties.path = path or "https://www.youtube.com/watch?v=fixture"
    p.properties.duration = 180
    p.properties["demuxer-via-network"] = true
    function p.load()
        p.properties["file-local-options/start"] = nil
        p.hook("on_load", 5)
        p.properties["user-data/mpv/ytdl/json-subprocess-result"] = {status = 0, stdout = "metadata"}
        p.hook("on_load", 20)
        p.fire("file-loaded")
    end
    function p.buffer()
        p.observe("paused-for-cache", true)
        return p.timers[#p.timers]
    end
    function p.recover()
        p.fire("end-file", {reason = "stop"})
        p.hook("on_after_end_file")
        p.properties["paused-for-cache"] = false
        p.load()
    end
    p.load()
    return p
end

local p = player()
for _, route in ipairs({"authenticated", "token", "hls", "fallback", "error"}) do
    p.observe("time-pos", 42)
    local timer = p.buffer()
    assert(timer.seconds == 10 and not timer.killed)
    p.observe("paused-for-cache", true)
    assert(p.timers[#p.timers] == timer, "duplicate buffering notification restarted the timer")
    p.clock = p.clock + 10
    timer.fn()
    assert(p.commands[#p.commands][1] == "stop")
    p.recover()
    assert(p.properties["user-data/youtube-quality/route"] == route, "buffer recovery repeated or skipped a route")
    if route ~= "error" then
        assert(p.properties["file-local-options/start"] == "42", "buffer recovery lost the position")
    end
end
assert(p.properties["user-data/youtube-quality/slate"], "fallback buffering caused an endless retry loop")
assert(p.overlay.data:find("Playback stalled while buffering.", 1, true), "failure screen lost the reason")
local count = #p.timers
p.buffer()
assert(#p.timers == count, "error screen started buffer recovery")

for _, property in ipairs({"pause", "seeking", "paused-for-cache"}) do
    local q = player()
    local timer = q.buffer()
    q.observe(property, property ~= "paused-for-cache")
    assert(timer.killed, "pause, seek, or resumed playback did not cancel recovery")
    assert(#q.commands == 0)
    q.observe(property, property == "paused-for-cache")
    assert(q.timers[#q.timers] ~= timer and q.timers[#q.timers].seconds == 10)
end
for _, info in ipairs({{is_live = true}, {live_status = "is_live"}, {live_status = "post_live"}, {live_status = "is_upcoming"}}) do
    local q = player(info)
    local before = #q.timers
    q.buffer()
    assert(#q.timers == before, "live stream started recorded-video recovery")
end
for _, path in ipairs({"/tmp/video.mp4", "https://example.org/video"}) do
    local q = player(nil, path)
    q.buffer()
    assert(#q.timers == 0, "unrelated media started YouTube recovery")
end
local q = player()
local timer = q.buffer()
q.fire("end-file", {reason = "stop"})
assert(timer.killed)
local before = #q.timers
q.observe("paused-for-cache", true)
assert(#q.timers == before, "unloaded file restarted buffer recovery")
q = player(nil, nil, "")
q.buffer().fn(); q.recover()
assert(q.properties["user-data/youtube-quality/route"] == "token", "automatic recovery tried unconfigured cookies")
q = player()
q.observe("time-pos", 65)
q.keys["Alt+q"](); q.recover()
assert(q.properties["user-data/youtube-quality/route"] == "fallback")
assert(q.properties["file-local-options/start"] == "65", "manual fallback lost the position")
for _, case in ipairs({
    {"ERROR: Sign in to confirm you are not a bot https://private.test/token", "account access"},
    {"ERROR: HTTP Error 429: Too Many Requests https://private.test/token", "limiting requests"},
    {"yt-dlp-mpv: extraction timed out", "timed out"},
    {"ERROR: Requested format is not available", "format is unavailable"},
}) do
    local r = player()
    r.observe("user-data/mpv/ytdl/json-subprocess-result", {status = 1, stderr = case[1]})
    local error = r.properties["user-data/youtube-quality/error"]
    assert(error:find(case[2], 1, true))
    assert(not error:find("private", 1, true), "failure reason exposed provider URLs")
end
print("Automatic buffer recovery: position, route progression, cancellation, scope, and safe errors passed")
