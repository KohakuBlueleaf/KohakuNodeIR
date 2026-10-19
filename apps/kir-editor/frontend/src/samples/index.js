import factorial from "./factorial.kir?raw"
import clamp from "./clamp.kir?raw"
import each from "./each.kir?raw"
import tour from "./tour.kir?raw"

/** Programs shipped with the editor; all run on the backend's `demo` library. */
export const SAMPLES = [
  { id: "tour", title: "Tour: @def, @try, switch, parallel, @dataflow", text: tour },
  { id: "factorial", title: "Factorial: a jump loop", text: factorial },
  { id: "each", title: "Each: a loop over boxes", text: each },
  { id: "clamp", title: "Clamp: a @def subgraph", text: clamp },
]
