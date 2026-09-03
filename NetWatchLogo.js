.pragma library

// The NetWatch wordmark.
//
// The Blackwall has had a logo since v1 and NetWatch had a line of text in the
// corner, which said the wrong thing about which of them the station belongs
// to. This is the post's own mark: the agency watching the wall, not a caption
// on the wall's monitor.
//
// Every line is padded to the same length so the block never has a ragged
// right edge under a gradient or a scan -- the same reason Logo.js pads.
// Drawn in NetWatch's colours rather than the wall's: the wall is red because
// it is the thing being contained, and the people watching it are not.

var ROWS = [
  "███╗   ██╗███████╗████████╗██╗    ██╗ █████╗ ████████╗ ██████╗██╗  ██╗",
  "████╗  ██║██╔════╝╚══██╔══╝██║    ██║██╔══██╗╚══██╔══╝██╔════╝██║  ██║",
  "██╔██╗ ██║█████╗     ██║   ██║ █╗ ██║███████║   ██║   ██║     ███████║",
  "██║╚██╗██║██╔══╝     ██║   ██║███╗██║██╔══██║   ██║   ██║     ██╔══██║",
  "██║ ╚████║███████╗   ██║   ╚███╔███╔╝██║  ██║   ██║   ╚██████╗██║  ██║",
  "╚═╝  ╚═══╝╚══════╝   ╚═╝    ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝"
]

var TEXT = ROWS.join("\n")

function rowCount() {
  return ROWS.length
}

function longestLine() {
  var longest = ""
  for (var i = 0; i < ROWS.length; i++)
    if (ROWS[i].length > longest.length) longest = ROWS[i]
  return longest
}
