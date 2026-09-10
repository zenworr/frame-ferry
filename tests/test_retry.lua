local mock = dofile("tests/mp_mock.lua")
local function player()
    local p = mock("config/mpv/scripts/youtube.lua", {options = {cookies_browser = "chromium:test"}})
    function p.load(url, raw)
        p.properties.path = url
        p.properties["options/ytdl-raw-options"] = raw or {["format-sort"] = "res:2160"}
        p.properties["file-local-options/ytdl-raw-options"] = nil
        p.properties["file-local-options/start"] = nil
        p.hook("on_load", 5)
    end
    function p.result(stderr, stdout)
        p.observe("user-data/mpv/ytdl/json-subprocess-result", {status = stdout and 1, stderr = stderr, stdout = stdout})
        p.hook("on_load", 15)
    end
    function p.finish(reason) p.fire("end-file", {reason = reason}); p.hook("on_after_end_file") end
    function p.loaded() p.fire("file-loaded") end
    function p.timeout()
        local t = p.timers[#p.timers]; assert(not t.killed)
        p.clock = p.clock + t.seconds; t.fn(); p.finish("stop")
    end
    function p.route() return p.properties["user-data/youtube-quality/route"] end
    return p
end

local url = "https://www.youtube.com/watch?v=example"
local a, b = player(), player()
for _, route in ipairs({"primary", "authenticated", "token", "hls", "fallback"}) do
    a.load(url)
    assert(a.route() == route)
    local raw = a.properties["file-local-options/ytdl-raw-options"]
    assert(raw["frameferry-route"] == route and raw["format-sort"] == "res:2160")
    assert(a.properties["options/ytdl-raw-options"]["frameferry-route"] == nil)
    assert(tonumber(raw["frameferry-timeout"]) < a.timers[#a.timers].seconds)
    if route == "authenticated" or route == "token" then
        assert(raw["cookies-from-browser"]:match("^chromium:"))
    else
        assert(raw["cookies-from-browser"] == nil)
    end
    a.finish("error")
end
a.load(url); a.loaded()
assert(a.route() == "error" and a.overlay.shown and a.properties.pause)
assert(a.properties["user-data/youtube-quality/slate"], "failure screen exposes a play button")
assert(a.properties["file-local-options/ytdl"] == nil, "failure screen unloads the extraction hook")
local count = #a.commands
a.finish("error")
assert(#a.commands == count, "retry loop after failure screen")
a.load(url)
assert(a.route() == "primary" and not a.overlay.shown and a.properties.pause == false)
a.finish("stop")
assert(#a.commands == count, "manual stop caused recovery")

b.load(url)
assert(b.route() == "primary", "retry state leaked between players")
b.loaded()
assert(b.timers[#b.timers].killed)
assert(not b.properties["user-data/youtube-quality/loading"])
b.observe("video-params", {w = 3840, h = 1920})
assert(b.properties["user-data/youtube-quality/badge"] == "4K")
local messages = #b.messages
b.observe("video-params", {w = 3840, h = 1920})
assert(#b.messages == messages, "duplicate playback notice")
b.observe("video-params", {w = 1920, h = 960})
assert(b.properties["user-data/youtube-quality/badge"] == "960p")
b.finish("eof")
assert(#b.commands == 0)
b.load("/tmp/local.mp4")
assert(not b.properties["user-data/youtube-quality/active"])
assert(not b.properties["user-data/youtube-quality/slate"])
assert(b.route() == "", "route leaked to local media")

local c = player()
c.load(url); c.result("ERROR: Sign in to confirm your age"); c.finish("error")
for _, route in ipairs({"authenticated", "token", "hls", "fallback"}) do
    c.load(url); assert(c.route() == route)
    assert(c.properties["file-local-options/ytdl-raw-options"]["cookies-from-browser"])
    c.finish("error")
end

local d = player()
for _, route in ipairs({"primary", "authenticated", "token", "fallback"}) do
    d.load(url); assert(d.route() == route); d.timeout()
    assert(d.commands[#d.commands - 1][1] == "stop")
    assert(d.commands[#d.commands - 1][2] == "keep-playlist")
end
d.load(url); assert(d.route() == "error")
local total = 0
for _, t in ipairs(d.timers) do total = total + t.seconds end
assert(total <= 30, "startup budget exceeded")

local e = player()
e.load(url); e.keys["Alt+q"](); e.finish("stop"); e.load(url)
assert(e.route() == "fallback", "quick fallback did not bypass quality attempts")
e.finish("stop"); e.load(url)
e.result("YouTube post-live DASH fragments lack reliable timing"); e.finish("error"); e.load(url)
assert(e.route() == "hls", "unsupported DASH did not skip to HLS")
e.finish("error"); e.load(url)
assert(e.route() == "fallback")
e.finish("stop"); e.load(url, {["cookies-from-browser"] = "chromium:test"})
e.finish("error"); e.load(url)
assert(e.route() == "token", "explicit cookies caused a duplicate authenticated attempt")

local retry = player()
retry.load(url); retry.keys["Ctrl+r"](); retry.finish("stop"); retry.load(url)
assert(retry.route() == "primary", "manual retry skipped the fresh primary attempt")
retry.keys["Ctrl+r"]()
local before_quit = #retry.commands
retry.finish("quit")
assert(#retry.commands == before_quit, "quit started another extraction")

local position = player()
position.load(url); position.loaded(); position.observe("time-pos", 30)
position.properties.duration = 60
position.properties["demuxer-via-network"] = true
position.properties.pause = true
position.keys["Ctrl+r"](); position.finish("stop"); position.load(url)
assert(position.properties["file-local-options/start"] == "30", "manual retry lost playback position")
position.loaded(); position.observe("time-pos", 42); position.finish("error")
for _, route in ipairs({"authenticated", "token", "hls", "fallback"}) do
    position.load(url); assert(position.route() == route)
    if route == "authenticated" then position.loaded() end
    position.finish("error")
end
position.load(url); position.loaded()
position.keys["Ctrl+r"](); position.finish("stop"); position.load(url)
assert(position.properties["file-local-options/start"] == "42", "retry after the error screen lost playback position")
position.finish("stop"); position.load(url)
assert(position.properties["file-local-options/start"] == nil, "position leaked into a new load")

local f = player()
f.load(url); f.result("YouTube post-live DASH fragments lack reliable timing")
f.keys["Ctrl+b"](); f.finish("stop"); f.load(url); f.loaded()
assert(f.route() == "browser", "browser request was replaced by automatic recovery")
assert(f.properties["file-local-options/force-media-title"] == "Continue in browser")
local g = player()
g.load(url .. "&t=1#old"); g.loaded(); g.observe("time-pos", 54)
g.properties.duration = 1800; g.properties["demuxer-via-network"] = true
g.finish("error"); g.load(url .. "&t=1#old")
assert(g.properties["file-local-options/start"] == "54", "recovery lost playback position")
g.loaded(); g.keys["Ctrl+b"]()
assert(g.properties.pause, "browser fallback did not pause playback")
assert(g.async_commands[#g.async_commands].args[2] == url .. "&t=54", "browser lost VOD position")

g.observe("time-pos", 0); g.keys["Ctrl+b"]()
assert(g.async_commands[#g.async_commands].args[2] == url .. "&t=0", "browser kept an old timestamp at zero")

local retained = player()
retained.load(url); retained.clock = 6; retained.finish("error")
retained.load(url)
retained.result("yt-dlp-mpv: limited authenticated formats; try token route", "{}")
retained.clock = 14; retained.finish("error")
retained.load(url); retained.clock = 22; retained.finish("error")
retained.load(url); assert(retained.route() == "retained", "earlier stream was discarded")
local candidate = retained.properties["file-local-options/ytdl-raw-options"]["frameferry-candidate"]
assert(type(candidate) == "string")
retained.timeout(); assert(not io.open(candidate), "candidate file leaked after failure")
retained.load(url); assert(retained.route() == "fallback", "retained stream caused a retry loop")
retained.timeout(); retained.load(url)
assert(retained.route() == "error" and retained.clock == 30, "retained stream extended the load budget")

for _, change in ipairs({"item", "quality"}) do
    local p = player()
    p.properties["playlist/0/id"] = "1"
    p.properties["ytdl-format"] = "best[height<=?2160]"
    p.load(url); p.finish("error"); p.load(url)
    p.result("yt-dlp-mpv: limited authenticated formats; try token route", "{}")
    p.finish("error")
    if change == "item" then p.properties["playlist/0/id"] = "2"
    else p.properties["ytdl-format"] = "best[height<=?720]" end
    p.load(url)
    assert(p.route() == "primary", "pending recovery leaked into a new item or quality choice")
    p.keys["Alt+q"](); p.finish("stop"); p.load(url)
    assert(p.route() == "fallback", "old candidate survived an item or quality change")
end

for _, other in ipairs({"https://example.org/video", "https://youtube.com.evil.test/video", "/tmp/video.mp4"}) do
    local p = player(); p.load(other); p.finish("error")
    assert(#p.commands == 0 and #p.timers == 0, "policy applied to unrelated media")
end
print("YouTube routes, UI state, cancellation, deadlines, cookies, and position: passed")
