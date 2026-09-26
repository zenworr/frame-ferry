std = "lua51"
max_line_length = 120

files["config/mpv/scripts/*.lua"] = {
  read_globals = {"mp"},
}

files["tests/*.lua"] = {
  std = "lua54",
}
