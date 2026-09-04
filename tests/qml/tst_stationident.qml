import QtQuick
import QtTest
import "../../"

// The ident strip. Decorative, but it is generated geometry, and generated
// geometry that escapes its box draws over its neighbours.
TestCase {
  name: "StationIdent"

  Component {
    id: identFactory
    StationIdent { width: 240; height: 15 }
  }

  function test_bars_stay_inside_the_strip() {
    var id = identFactory.createObject(null, { clock: 0 })
    verify(id.bars.length > 0)
    for (var i = 0; i < id.bars.length; i++) {
      var b = id.bars[i]
      verify(b.x >= 0)
      verify(b.x + b.w <= id.width)
    }
    id.destroy()
  }

  function test_the_pattern_is_the_same_pattern_every_time() {
    // An ident that came out differently on every open would not be an ident.
    var a = identFactory.createObject(null, { clock: 0 })
    var b = identFactory.createObject(null, { clock: 40 })
    compare(a.bars.length, b.bars.length)
    for (var i = 0; i < a.bars.length; i++) compare(a.bars[i].x, b.bars[i].x)
    a.destroy(); b.destroy()
  }

  function test_the_head_parks_off_the_strip_between_passes() {
    // -1 is "resting", and the head must not be drawn at the left edge while
    // it waits.
    var id = identFactory.createObject(null, { clock: 0 })
    id.clock = id.sweepSeconds + 0.4
    compare(id.reading, false)
    id.clock = 0.1
    compare(id.reading, true)
    id.destroy()
  }

  function test_a_zero_width_strip_produces_no_bars() {
    var id = identFactory.createObject(null, { clock: 0 })
    id.width = 0
    id.rebuild()
    compare(id.bars.length, 0)
    id.destroy()
  }
}
