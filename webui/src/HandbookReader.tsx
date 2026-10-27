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
    [data, setData] = useState<Handbook | null>(null),
    [selected, setSelected] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [retry, setRetry] = useState(0);
  const article = useRef<HTMLDivElement>(null),
    savedScroll = useRef<Record<string, number>>({}),
    section = useRef<HTMLDivElement>(null);
  const chapters = useMemo(() => splitChapters(data?.markdown || ""), [data]);
  const chapter = chapters.find((c) => c.id === selected) || chapters[0];
  useEffect(() => {
    if (!visible) return;
    let active = true;
    const api = createApi(options);
    setError("");
    setNotice("");
    setData(null);
    api
      .handbook(document, release)
      .then((d) => {
        if (active) setData(d);
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
      if (target.stage && document === "handbook")
        setSelected(
          all.find((c) => c.stageId === target.stage)?.id || all[0]?.id || "",
        );
      else
        setSelected((s) =>
          all.some((c) => c.id === s) ? s : all[0]?.id || "",
        );
    }
  }, [data, target.serial]);
  useEffect(() => {
    const element = article.current;
    if (!visible || !data || !chapter || !element || !options.renderMarkdown)
      return;
    const key = `${document}/${chapter.id}`;
    element.replaceChildren();
    let handle: { unmount(): void } | undefined;
    try {
      handle = options.renderMarkdown(element, {
        markdown: chapter.markdown,
      });
    } catch {
      setError("阅读组件暂不可用");
    }
    if (section.current)
      section.current.scrollTop = savedScroll.current[key] || 0;
    return () => {
      if (section.current) savedScroll.current[key] = section.current.scrollTop;
      handle?.unmount();
    };
  }, [visible, data, chapter, document, options.renderMarkdown]);
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
      const element = [
        ...article.current.querySelectorAll<HTMLElement>("[id]"),
      ].find((e) => e.id === id);
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
                aria-current={c.id === chapter?.id ? "page" : undefined}
                onClick={() => setSelected(c.id)}
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
