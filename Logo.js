.pragma library

// The Blackwall centrepiece, exactly as specified. Every line is padded to the
// same width so the ripple slices below can clip it on a fixed character grid
// without the rows drifting against each other.
//
// Generated from logo.txt; edit that file and regenerate, or edit here
// directly — plugin code under ~/.config/omarchy/plugins/ hot-reloads on save.
var LINES = [
  "▀█████████▄   ▄█          ▄████████  ▄████████    ▄█   ▄█▄  ▄█     █▄     ▄████████  ▄█        ▄█       ",
  "  ███    ███ ███         ███    ███ ███    ███   ███ ▄███▀ ███     ███   ███    ███ ███       ███       ",
  "  ███    ███ ███         ███    ███ ███    █▀    ███▐██▀   ███     ███   ███    ███ ███       ███       ",
  " ▄███▄▄▄██▀  ███         ███    ███ ███         ▄█████▀    ███     ███   ███    ███ ███       ███       ",
  "▀▀███▀▀▀██▄  ███       ▀███████████ ███        ▀▀█████▄    ███     ███ ▀███████████ ███       ███       ",
  "  ███    ██▄ ███         ███    ███ ███    █▄    ███▐██▄   ███     ███   ███    ███ ███       ███       ",
  "  ███    ███ ███▌    ▄   ███    ███ ███    ███   ███ ▀███▄ ███ ▄█▄ ███   ███    ███ ███▌    ▄ ███▌    ▄ ",
  "▄█████████▀  █████▄▄██   ███    █▀  ████████▀    ███   ▀█▀  ▀███▀███▀    ███    █▀  █████▄▄██ █████▄▄██ ",
  "             ▀                                   ▀                                  ▀         ▀         ",
]

var TEXT = LINES.join("\n")

// Widest row, used to size the font so the whole wall fits the screen.
function longestLine() {
  var longest = ""
  for (var i = 0; i < LINES.length; i++)
    if (LINES[i].length > longest.length) longest = LINES[i]
  return longest
}

function rowCount() {
  return LINES.length
}
