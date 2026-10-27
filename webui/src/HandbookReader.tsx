import { useEffect, useMemo, useRef, useState } from "react";
import { createApi } from "./api";
import type { MountOptions } from "./types";
import { splitChapters } from "./handbook";
import { message, type Handbook, type DocumentName } from "./projects/types";
export function HandbookReader({
  options,
  visible,
  target,
  onBack,
  onLegacy,
  release,
}: {
  options: MountOptions;
  release?: string;
  visible: boolean;
  target: { stage?: string; serial: number };
  onBack: () => void;
  onLegacy: () => void;
}) {
  const [document, setDocument] = useState<DocumentName>("handbook"),
    [loaded, setLoaded] = useState<{
      document: DocumentName; targetSerial: number; data: Handbook;
    } | null>(null),
    [selected, setSelected] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [retry, setRetry] = useState(0);
  const data = loaded?.document === document && loaded.targetSerial === target.serial
    ? loaded.data : null;
  const [jump, setJump] = useState({
    id: "", serial: 0, targetSerial: target.serial, document: "handbook" as DocumentName,
  });
  const completedJump = useRef(0);
  const appliedStageTarget = useRef<number | null>(null);
  const article = useRef<HTMLDivElement>(null),
    savedScroll = useRef<Record<string, number>>({}),
    section = useRef<HTMLDivElement>(null);
  const chapters = useMemo(() => splitChapters(data?.markdown || ""), [data]);
  const chapter = chapters.find((c) => c.id === selected) || chapters[0];
  const headingIds = useMemo(
    () => Object.fromEntries(
      chapters.filter((c) => c.line !== null).map((c) => [c.line!, c.id]),
    ),
    [chapters],
  );
  useEffect(() => {
    if (!visible) return;
    let active = true;
    const api = createApi(options);
    setError("");
    setNotice("");
    setLoaded(null);
    api
      .handbook(document, release)
      .then((d) => {
        if (active) setLoaded({ document, targetSerial: target.serial, data: d });
      })
      .catch((e) => {
        if (active) setError(message(e));
      });
    return () => {
      active = false;
      api.dispose();
    };
  }, [
    visible,
    document,
    target.serial,
    retry,
    release,
    options.apiBase,
    options.csrfToken,
    options.onAuthError,
  ]);
  useEffect(() => {
    if (target.stage) {
      setDocument("handbook");
      setSelected("");
    }
  }, [target.serial, target.stage]);
  useEffect(() => {
    if (data) {
      const all = splitChapters(data.markdown);
      if (target.stage && document === "handbook" && appliedStageTarget.current !== target.serial) {
        const id = all.find((c) => c.stageId === target.stage)?.id || all[0]?.id || "";
        setSelected(id);
        setJump((old) => ({ id, serial: old.serial + 1, targetSerial: target.serial, document }));
        appliedStageTarget.current = target.serial;
      }
      else
        setSelected((s) =>
          all.some((c) => c.id === s) ? s : all[0]?.id || "",
        );
    }
  }, [data, target.serial]);
  useEffect(() => {
    const element = article.current;
    if (!visible || !data || !element || !options.renderMarkdown) return;
    const key = document;
    const body = section.current;
    element.replaceChildren();
    let handle: { unmount(): void } | undefined;
    try {
      handle = options.renderMarkdown(element, {
        markdown: data.markdown,
        headingIds,
      });
    } catch {
      setError("阅读组件暂不可用");
    }
    // Native React rendering is asynchronous; restore only after content exists.
    const restore = () => {
      if (!element.querySelector("h1,h2,h3,p,table,pre,figure")) return false;
      if (body) body.scrollTop = savedScroll.current[key] || 0;
      return true;
    };
    const observer = new MutationObserver(() => {
      if (restore()) observer.disconnect();
    });
    if (!restore()) observer.observe(element, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (body) savedScroll.current[key] = body.scrollTop;
      handle?.unmount();
    };
  }, [visible, data, headingIds, document, options.renderMarkdown]);
  useEffect(() => {
    const element = article.current;
    if (
      !visible || !data || !jump.id || !element ||
      jump.document !== document || jump.targetSerial !== target.serial ||
      completedJump.current === jump.serial
    ) return;
    const scroll = () => {
      const target = chapters.find((c) => c.id === jump.id);
      if (target?.line === null) {
        if (!element.textContent) return false;
        if (section.current) section.current.scrollTop = 0;
        completedJump.current = jump.serial;
        return true;
      }
      const destination = [...element.querySelectorAll<HTMLElement>("[id]")]
        .find((node) => node.id === jump.id);
      if (!destination) return false;
      destination.scrollIntoView?.({ block: "start" });
      completedJump.current = jump.serial;
      return true;
    };
    const observer = new MutationObserver(() => {
      if (scroll()) observer.disconnect();
    });
    if (!scroll()) observer.observe(element, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [visible, data, jump, document, chapters, target.serial]);
  function follow(event: React.MouseEvent) {
    const a = (event.target as Element).closest("a");
    if (!a || !article.current?.contains(a)) return;
    const href = a.getAttribute("href") || "";
    if (href.startsWith("#")) {
      event.preventDefault();
      let id = "";
      try {
        id = decodeURIComponent(href.slice(1));
      } catch {
        return;
      }
      let element = [
        ...article.current.querySelectorAll<HTMLElement>("[id]"),
      ].find((e) => e.id === id);
      // Preserve author-written Markdown hashes when TOC IDs override headings.
      if (!element) {
        const counts = new Map<string, number>();
        for (const heading of article.current.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6")) {
          const base = (heading.textContent || "").normalize("NFKC").trim()
            .toLocaleLowerCase("zh-CN").replace(/\s+/g, "-")
            .replace(/[^\p{Letter}\p{Number}_-]/gu, "") || "section";
          const count = (counts.get(base) || 0) + 1;
          counts.set(base, count);
          if ((count === 1 ? base : `${base}-${count}`) === id) {
            element = heading;
            break;
          }
        }
      }
      element?.scrollIntoView?.({ block: "start" });
      return;
    }
    // A fixed document selector, never a path passed through to the API.
    if (
      /^(?:\.\/|\.\.\/docs\/|docs\/)?(?:manufacturing-workflow\.md|workflows\/manufacturing-process-overview\.md)(?:#.*)?$/.test(
        href,
      )
    ) {
      event.preventDefault();
      setNotice("");
      setDocument("workflow");
      setSelected("");
      return;
    }
    if (
      /^(?:\.\/|\.\.\/|\.\.\/docs\/|docs\/)?manufacturing-system-handbook\.md(?:#.*)?$/.test(
        href,
      )
    ) {
      event.preventDefault();
      setNotice("");
      setDocument("handbook");
      setSelected("");
      return;
    }
    if (href && !/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) {
      event.preventDefault();
      setNotice(
        `“${a.textContent?.trim() || "该参考资料"}”尚未纳入本次发布，当前阅读内容已保留。`,
      );
    }
  }
  return (
    <div hidden={!visible} className="mf-handbook">
      <div className="mf-section-heading">
        <div>
          <h2>{data?.title || "制造手册"}</h2>
          {data && (
            <p className="mf-meta">
              更新 {data.updated_at.replace("T", " ").slice(0, 16)} ·{" "}
              {data.source_path} · {data.release}
            </p>
          )}
        </div>
        <div className="mf-actions">
          <button onClick={onBack}>返回工作内容</button>
          <button className="mf-link mf-small" onClick={onLegacy}>
            流程现状参考
          </button>
        </div>
      </div>
      <div className="mf-actions mf-book-switch">
        <button
          aria-pressed={document === "handbook"}
          onClick={() => {
            setDocument("handbook");
            setSelected("");
          }}
        >
          系统手册
        </button>
        <button
          aria-pressed={document === "workflow"}
          onClick={() => {
            setDocument("workflow");
            setSelected("");
          }}
        >
          工作流总览
        </button>
      </div>
      {notice && (
        <p className="mf-badge" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="mf-error" role="alert">
          {error}{" "}
          <button onClick={() => setRetry((x) => x + 1)}>重试读取手册</button>
        </p>
      )}
      {!data && !error && visible && <p role="status">正在读取手册…</p>}
      {data && (
        <div className="mf-book-grid">
          <nav className="mf-chapter-nav" aria-label="手册章节">
            {chapters.map((c) => (
              <button
                key={c.id}
                aria-current={c.id === chapter?.id ? "location" : undefined}
                onClick={() => {
                  setSelected(c.id);
                  setJump((old) => ({ id: c.id, serial: old.serial + 1, targetSerial: target.serial, document }));
                }}
              >
                {c.title}
              </button>
            ))}
          </nav>
          <div className="mf-book-body" ref={section}>
            {!options.renderMarkdown ? (
              <p role="status">阅读组件暂不可用，请重新加载页面。</p>
            ) : (
              <div
                className="mf-article"
                ref={article}
                onClickCapture={follow}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
