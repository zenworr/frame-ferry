local mock = dofile("tests/mp_mock.lua")
local url = "https://www.youtube.com/watch?v=example"
local function stream(protocol)
    return {protocol = protocol or "https", url = "https://media.example/video"}
end
local function player(info, version, path, status, existing)
    local p = mock("config/mpv/scripts/youtube.lua", {utils = {parse_json = function() return info end}})
    p.properties.path = path or url
    p.properties["ffmpeg-version"] = version or "n9.0.1"
    p.properties["file-local-options/stream-lavf-o"] = existing
    p.properties["options/network-timeout"] = 60
    p.hook("on_load", 5)
    p.properties["user-data/mpv/ytdl/json-subprocess-result"] = {status = status or 0, stdout = "metadata"}
    p.hook("on_load", 20)
    return p
end

for _, version in ipairs({"9.0", "n9.0.1", "10.0-dev"}) do
    local p = player({requested_formats = {stream(), stream("http")}, formats = {stream("m3u8_native")}}, version)
    local opts = p.properties["file-local-options/stream-lavf-o"]
    assert(opts.request_size == "1048576" and opts.multiple_requests == "1" and opts.short_seek_size == "1048576")
    p.fire("file-loaded")
    assert(p.properties["options/network-timeout"] == 60)
    assert(p.properties["file-local-options/network-timeout"] == nil)
end
assert(player({requested_downloads = {stream()}}).properties["file-local-options/stream-lavf-o"].request_size)

for _, version in ipairs({"n8.0", "7.1", "git-unknown", ""}) do
    assert(player(stream(), version).properties["file-local-options/stream-lavf-o"] == nil)
end
for _, path in ipairs({"https://example.org/video", "https://youtube.com.evil.test/video", "/tmp/video.mp4"}) do
    assert(player(stream(), nil, path).properties["file-local-options/stream-lavf-o"] == nil)
end
for _, info in ipairs({
    false,
    {url = "https://media.example/video"},
    stream("m3u8_native"),
    stream("http_dash_segments"),
    {protocol = "https", url = "memory://video"},
    {requested_formats = {}},
    {requested_formats = {stream(), stream("m3u8_native")}},
    {requested_formats = {{protocol = "https", url = "https://media.example/video", fragments = {}}}},
    {is_live = true, requested_formats = {stream()}},
    {live_status = "is_live", requested_formats = {stream()}},
    {live_status = "post_live", requested_formats = {stream()}},
}) do
    assert(player(info).properties["file-local-options/stream-lavf-o"] == nil, "transport changed for unsupported media")
end
assert(player(stream(), nil, nil, 1).properties["file-local-options/stream-lavf-o"] == nil)
local original = {cookies = "private", http_proxy = "http://localhost:8080", request_size = "0", multiple_requests = "0", short_seek_size = "4096"}
local p = player(stream(), nil, nil, nil, original)
for key, value in pairs(original) do
    assert(p.properties["file-local-options/stream-lavf-o"][key] == value, "existing transport option was overwritten")
end
print("YouTube bounded requests: stream scope, FFmpeg compatibility, timeouts, and user options passed")
