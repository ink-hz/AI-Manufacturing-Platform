export interface Chapter {
  id: string;
  title: string;
  markdown: string;
  line: number | null;
  stageId?: string;
}
/** Slice the original string, never reconstruct it: preambles and part overviews are content. */
export function splitChapters(markdown: string): Chapter[] {
  const starts: { offset: number; title: string; line: number | null; stageId?: string }[] = [];
  let offset = 0,
    lineNumber = 0,
    fence = "",
    fenceLength = 0;
  for (const line of markdown.match(/[^\n]*\n|[^\n]+$/g) || []) {
    lineNumber++;
    const marker = /^ {0,3}(`{3,}|~{3,})(.*?)(?:\r?\n)?$/.exec(line);
    if (marker) {
      if (!fence) {
        fence = marker[1][0];
        fenceLength = marker[1].length;
      } else if (
        marker[1][0] === fence &&
        marker[1].length >= fenceLength &&
        !marker[2].trim()
      ) {
        fence = "";
      }
      offset += line.length;
      continue;
    }
    if (!fence) {
      const h = /^ {0,3}(#{1,2})\s+(.+?)(?:\s+#+)?\s*$/.exec(line.trimEnd());
      if (h) {
        const stage =
          h[1] === "##"
            ? /^(?:\d+[.．、]\s*)?(S[1-9])(?:\s|[:：、.—-]|$)/.exec(h[2])
            : null;
        starts.push({
          offset,
          title: h[2],
          line: lineNumber,
          ...(stage ? { stageId: stage[1] } : {}),
        });
      }
    }
    offset += line.length;
  }
  if (!starts.length || starts[0].offset > 0)
    starts.unshift({ offset: 0, title: "导读", line: null });
  return starts.map((s, i) => ({
    id: `mf-chapter-${i}`,
    title: s.title,
    line: s.line,
    stageId: s.stageId,
    markdown: markdown.slice(
      s.offset,
      starts[i + 1]?.offset ?? markdown.length,
    ),
  }));
}
