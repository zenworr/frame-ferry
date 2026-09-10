local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for k, v in pairs(value) do result[k] = copy(v) end
    return result
end

return function(script, overrides)
    overrides = overrides or {}
    local p = {properties = {}, hooks = {}, priorities = {}, events = {}, observers = {}, keys = {}, bindings = {},
        commands = {}, async_commands = {}, timers = {}, messages = {}, clock = 0}
    p.overlay = {remove = function(self) self.shown = false end,
        update = function(self) self.shown = true end}
    local function get(name, default)
        if p.properties[name] ~= nil then return copy(p.properties[name]) end
        return default
    end
    local function set(name, value) p.properties[name] = copy(value) end
    local function register(list, name, fn)
        list[name] = list[name] or {}
        table.insert(list[name], fn)
    end
    local function timer(seconds, fn)
        local t = {seconds = seconds, fn = fn, killed = false,
            kill = function(self) self.killed = true end, resume = function(self) self.killed = false end}
        table.insert(p.timers, t)
        return t
    end
    local msg = {info = function() end, warn = function() end, error = function() end, debug = function() end}
    local mp = {
        msg = msg,
        create_osd_overlay = function() return p.overlay end,
        add_hook = function(name, priority, fn)
            register(p.hooks, name, fn)
            p.priorities[fn] = priority
        end,
        register_event = function(name, fn) register(p.events, name, fn) end,
        observe_property = function(name, _, fn) register(p.observers, name, fn) end,
        add_key_binding = function(key, name, fn)
            if key then p.keys[key] = fn end
            p.bindings[name] = fn
        end,
        register_script_message = function(name, fn) p.bindings[name] = fn end,
        get_property = get, get_property_native = get, get_property_bool = get, get_property_number = get,
        set_property = set, set_property_native = set, set_property_bool = set, set_property_number = set,
        get_time = function() return p.clock end,
        add_timeout = timer, add_periodic_timer = timer,
        osd_message = function(text, seconds) table.insert(p.messages, {text, seconds}) end,
        commandv = function(...) table.insert(p.commands, {...}) end,
        command_native = function(args)
            assert(args[1] == "expand-path")
            return args[2]:gsub("^~~/", "/mpv-config/")
        end,
        command_native_async = function(args, callback)
            table.insert(p.async_commands, args)
            callback(true, {status = 0})
        end,
    }
    local function dispatch(list, name, ...)
        for _, fn in ipairs(list[name] or {}) do fn(...) end
    end
    function p.hook(name, priority)
        for _, fn in ipairs(p.hooks[name] or {}) do
            if not priority or p.priorities[fn] == priority then fn() end
        end
    end
    function p.fire(name, ...) dispatch(p.events, name, ...) end
    function p.observe(name, value) set(name, value); dispatch(p.observers, name, name, value) end
    local env = setmetatable({mp = mp, io = overrides.io or io, require = function(name)
        if name == "mp.msg" then return msg end
        if name == "mp.options" then return {read_options = function(options)
            for k, v in pairs(overrides.options or {}) do options[k] = v end
        end} end
        return require(name)
    end}, {__index = _G})
    assert(loadfile(script, "t", env))()
    for name in pairs(p.observers) do p.observe(name, p.properties[name]) end
    return p
end
