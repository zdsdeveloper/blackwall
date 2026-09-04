import QtQuick
import QtTest
import "../../"
import "../../Model.js" as Model

// The two panels that read out the operator rather than the wall.
//
// Model.activityReadout decides what the numbers are and is tested in
// tests/model.test.js. What is left here is what the panels do with them, and
// every one of these is a way the pair could quietly say the wrong thing: a
// countdown that keeps ticking while the count is held, a bar that fills the
// wrong way, a stretch shown as real when nothing is counting.
TestCase {
  name: "StationPost"

  Component { id: vigilFactory; StationVigil {} }
  Component { id: standFactory; StationStandDown {} }

  readonly property int oneMinute: 60000

  // A readout as the station would have computed it, with no projection: the
  // panels are handed a finished reading and never do this arithmetic.
  function reading(activeMinutes, opts) {
    var o = opts || {}
    var cfg = Model.parseActivity({
      enabled: o.enabled === false ? false : true,
      breakAfterMinutes: o.breakAfter === undefined ? 180 : o.breakAfter,
      idleResetMinutes: 15
    })
    return Model.activityReadout(cfg,
      { activeMs: activeMinutes * 60000, idleMs: (o.idleMinutes || 0) * 60000 },
      0, 0, o.away === true)
  }

  // ---- the vigil ----------------------------------------------------------

  function test_the_stretch_is_shown_as_a_running_time() {
    var v = vigilFactory.createObject(null, { readout: reading(147), height: 120 })
    compare(v.elapsed, "2:27:00")
    verify(v.counting)
    v.destroy()
  }

  function test_nothing_counting_shows_no_stretch_at_all() {
    // Not "0:00:00", which would read as a stretch that just started. The
    // count is off; there is no stretch to report.
    var v = vigilFactory.createObject(null, { readout: reading(147, { enabled: false }) })
    compare(v.counting, false)
    compare(v.elapsed, "--:--")
    compare(v.fraction, 0)
    v.destroy()
  }

  function test_the_bar_fills_with_the_stretch() {
    var v = vigilFactory.createObject(null, { readout: reading(90) })
    compare(v.fraction, 0.5)
    v.destroy()
  }

  function test_away_is_said_rather_than_left_to_be_inferred() {
    var v = vigilFactory.createObject(null, { readout: reading(90, { away: true }) })
    verify(v.away)
    // Still true, still shown -- it is simply not moving.
    compare(v.elapsed, "1:30:00")
    v.destroy()
  }

  function test_due_is_carried_through_to_the_bar() {
    var v = vigilFactory.createObject(null, { readout: reading(180) })
    verify(v.due)
    compare(v.fraction, 1)
    v.destroy()
  }

  // ---- the stand-down countdown -------------------------------------------

  function test_the_countdown_is_what_is_left_not_what_is_spent() {
    var s = standFactory.createObject(null, { readout: reading(147), caret: 1 })
    compare(s.leftMs, 33 * oneMinute)
    compare(s.face, "33:00")
    s.destroy()
  }

  function test_the_bar_empties_as_the_vigils_fills() {
    // Same instant, same reading, opposite bars. This is the pair's whole
    // shape: if both filled, one of them would be lying.
    var r = reading(135)
    var v = vigilFactory.createObject(null, { readout: r })
    var s = standFactory.createObject(null, { readout: r })
    compare(v.fraction, 0.75)
    compare(s.barLevel, 0.25)
    v.destroy()
    s.destroy()
  }

  function test_the_colon_blinks_while_it_runs() {
    var s = standFactory.createObject(null, { readout: reading(147), caret: 1 })
    compare(s.face, "33:00")
    s.caret = 0
    compare(s.face, "33 00")
    s.destroy()
  }

  function test_a_held_countdown_does_not_blink() {
    // The load-bearing one. A blinking colon means time is running, and while
    // they are away it is not: the whole point of the held state is that the
    // stretch is not advancing, so the panel must not animate as though it is.
    var s = standFactory.createObject(null, { readout: reading(147, { away: true }), caret: 0 })
    compare(s.face, "33:00")
    verify(s.away)
    s.destroy()
  }

  function test_past_due_it_reads_zero_rather_than_going_negative() {
    var s = standFactory.createObject(null, { readout: reading(400), caret: 1 })
    verify(s.due)
    compare(s.face, "00:00")
    compare(s.leftMs, 0)
    s.destroy()
  }

  function test_the_last_five_minutes_are_marked() {
    var s = standFactory.createObject(null, { readout: reading(176) })
    verify(s.closing)
    compare(s.faceColor, s.warnColor)
    s.destroy()
  }

  function test_and_before_that_they_are_not() {
    var s = standFactory.createObject(null, { readout: reading(174) })
    compare(s.closing, false)
    compare(s.faceColor, s.glowColor)
    s.destroy()
  }

  function test_nothing_counting_shows_no_countdown() {
    var s = standFactory.createObject(null, { readout: reading(147, { enabled: false }) })
    compare(s.counting, false)
    compare(s.face, "--:--")
    compare(s.due, false)
    compare(s.closing, false)
    compare(s.barLevel, 0)
    s.destroy()
  }

  // ---- what a missing service looks like ----------------------------------

  function test_no_readout_at_all_is_simply_off() {
    // The panel binds these to a service that may not have been mounted yet.
    // An undefined readout must read as "not counting", never as a stretch of
    // zero that is about to become a demand.
    var v = vigilFactory.createObject(null, {})
    var s = standFactory.createObject(null, {})
    compare(v.counting, false)
    compare(v.elapsed, "--:--")
    compare(s.counting, false)
    compare(s.face, "--:--")
    compare(s.due, false)
    v.destroy()
    s.destroy()
  }
}
