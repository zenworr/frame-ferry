local options = {categories = "sponsor", interval = 0.10, lead_time = 0.25}
require("mp.options").read_options(options, "sponsorblock_chapter_skip")

local enabled, ranges, timer = true, {}, nil
local categories = {}
for category in options.categories:gmatch("[^,]+") do
    categories[category:match("^%s*(.-)%s*$"):lower():gsub(" ", "_")] = true
end

local function update_activity()
    mp.set_property_bool("user-data/sponsorblock/available", #ranges > 0)
    mp.set_property("user-data/sponsorblock/state", enabled and "On" or "Off")
    if enabled and #ranges > 0 and not mp.get_property_bool("pause", false) then
        timer:resume()
    else
        timer:kill()
    end
end

local function refresh_ranges(_, chapters)
    local starts, found = {}, {}
    for _, chapter in ipairs(chapters or {}) do
        local category, edge, id = (chapter.title or ""):match("^(.+) segment (%a+) %(([^%)]+)%)$")
        if category and categories[category:lower():gsub(" ", "_")] then
            if edge == "start" then
                starts[id] = chapter.time
            elseif edge == "end" and starts[id] and chapter.time > starts[id] then
                found[#found + 1] = {start_time = starts[id], end_time = chapter.time}
            end
        end
    end
    table.sort(found, function(a, b) return a.start_time < b.start_time end)
    ranges = {}
    for _, range in ipairs(found) do
        local previous = ranges[#ranges]
        if previous and range.start_time <= previous.end_time then
            previous.end_time = math.max(previous.end_time, range.end_time)
        else
            ranges[#ranges + 1] = range
        end
    end
    update_activity()
end

local function check_ranges()
    if not enabled or mp.get_property_bool("pause", false) then return end
    local pos = mp.get_property_number("time-pos")
    if not pos then return end
    for _, range in ipairs(ranges) do
        if pos >= range.start_time - options.lead_time and pos < range.end_time then
            mp.osd_message("SponsorBlock: skipped segment")
            mp.set_property_number("time-pos", range.end_time)
            return
        end
    end
end

timer = mp.add_periodic_timer(options.interval, check_ranges)
timer:kill()
mp.observe_property("chapter-list", "native", refresh_ranges)
mp.observe_property("pause", "bool", update_activity)
mp.register_event("start-file", function()
    ranges = {}
    update_activity()
end)
mp.add_key_binding("Alt+s", "sponsorblock-toggle", function()
    enabled = not enabled
    update_activity()
    mp.osd_message("SponsorBlock: " .. (enabled and "on" or "off"))
end)
