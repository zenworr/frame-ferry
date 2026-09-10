local mock = dofile("tests/mp_mock.lua")
local p = mock("config/mpv/scripts/sponsorblock_chapter_skip.lua")
local timer = p.timers[1]
assert(timer.killed, "idle player still polls")
local function chapter(time, category, edge, id)
    return {time = time, title = category .. " segment " .. edge .. " (" .. id .. ")"}
end
p.observe("chapter-list", {
    chapter(10, "sponsor", "start", "a"), chapter(15, "sponsor", "start", "b"),
    chapter(20, "sponsor", "end", "a"), chapter(25, "sponsor", "end", "b"),
    chapter(30, "intro", "start", "c"), chapter(35, "intro", "end", "c"),
    chapter(40, "sponsor", "end", "orphan"), {time = 45, title = "Ordinary chapter"},
})
assert(not timer.killed and p.properties["user-data/sponsorblock/available"])
p.properties["time-pos"] = 9.8; timer.fn()
assert(p.properties["time-pos"] == 25, "overlapping segments did not merge")
p.properties["time-pos"] = 32; timer.fn()
assert(p.properties["time-pos"] == 32, "unselected category was skipped")
p.observe("pause", true)
assert(timer.killed, "paused player still polls")
p.properties["time-pos"] = 12; timer.fn()
assert(p.properties["time-pos"] == 12, "paused playback was moved")
p.observe("pause", false)
assert(not timer.killed)
p.keys["Alt+s"]()
assert(timer.killed and p.properties["user-data/sponsorblock/state"] == "Off")
p.keys["Alt+s"](); timer.fn()
assert(p.properties["time-pos"] == 25)
p.fire("start-file")
assert(timer.killed and not p.properties["user-data/sponsorblock/available"], "ranges leaked to next file")
print("SponsorBlock categories, overlap, lead time, pause, toggle, and idle polling: passed")
