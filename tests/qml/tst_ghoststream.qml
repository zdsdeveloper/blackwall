import QtQuick
import QtTest
import "../../"

// The mini-game's bookkeeping.
//
// It is a toy and touches nothing the daemon owns, so the risk is not
// correctness of the wall -- it is that a leak here runs for as long as the
// station is open. Ghosts have to be reaped whether they are clicked or not.
TestCase {
  name: "GhostStream"

  Component {
    id: streamFactory
    GhostStream { width: 200; height: 300 }
  }

  function make() {
    return streamFactory.createObject(null, { clock: 0, power: 1 })
  }

  function test_spawning_adds_one() {
    var s = make()
    compare(s.count, 0)
    s.spawn()
    compare(s.count, 1)
    s.destroy()
  }

  function test_spawning_is_capped() {
    // Otherwise a station left open all day accumulates delegates for ever.
    var s = make()
    for (var i = 0; i < 60; i++) s.spawn()
    verify(s.count <= 10)
    s.destroy()
  }

  function test_nothing_spawns_without_power() {
    // The station's clock stops when the window closes, and so must this.
    var s = streamFactory.createObject(null, { clock: 0, power: 0 })
    for (var i = 0; i < 5; i++) s.spawn()
    compare(s.count, 0)
    s.destroy()
  }

  function test_one_that_reaches_the_bottom_is_reaped() {
    // Unclicked ghosts leave the sector. If they were not reaped the column
    // would fill with delegates falling for ever below the fold.
    var s = make()
    s.spawn()
    compare(s.count, 1)
    // Far enough down that even a full face height is past the bottom.
    s.clock = 1000
    s.reap()
    compare(s.count, 0)
    s.destroy()
  }

  function test_one_still_falling_is_left_alone() {
    var s = make()
    s.spawn()
    s.clock = 0.2
    s.reap()
    compare(s.count, 1)
    s.destroy()
  }

  function test_reaping_an_empty_column_is_not_a_crash() {
    var s = make()
    s.reap()
    compare(s.count, 0)
    s.destroy()
  }
}
