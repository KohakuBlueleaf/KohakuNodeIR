/** Browser file I/O: download a text file, or pick local files to read. */

export function saveFile(name, content, mime = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type: `${mime};charset=utf-8` }))
  const a = document.createElement("a")
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Resolves to `[{name, text}]` for the files the user picked (empty when cancelled). */
export function pickFiles(accept, multiple = false) {
  return new Promise((resolve) => {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = accept
    input.multiple = multiple
    input.addEventListener("change", async () => {
      const files = [...(input.files || [])]
      resolve(await Promise.all(files.map(async (f) => ({ name: f.name, text: await f.text() }))))
    })
    input.addEventListener("cancel", () => resolve([]))
    input.click()
  })
}
