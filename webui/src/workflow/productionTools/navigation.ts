import { useEffect, useRef, useState } from "react";
import type { Location } from "./context";
/** Browser traversal is rolled back before a save/leave decision; UI and native history agree while blocked. */
export function useProductionNavigation({
  userId,
  location,
  apply,
  snapshot,
  guard,
}: {
  userId: string;
  location: Location;
  apply: (l: Location) => void;
  snapshot: () => Location;
  guard: (next: Location) => Promise<boolean>;
}) {
  const [index, setIndex] = useState(0),
    [blocked, setBlocked] = useState<null | (() => Promise<void>)>(null);
  const entries = useRef<Location[]>([location]),
    accepted = useRef(0),
    native = useRef(0),
    session = useRef(crypto.randomUUID()),
    busy = useRef(false),
    alive = useRef(true);
  const callbacks = useRef({ apply, snapshot, guard });
  callbacks.current = { apply, snapshot, guard };
  const travel = useRef<{ target: number; finish: () => void } | null>(null);
  const move = (target: number) =>
    new Promise<void>((finish) => {
      if (target === native.current) {
        finish();
        return;
      }
      travel.current = { target, finish };
      window.history.go(target - native.current);
    });
  const commit = (next: Location, target: number) => {
    accepted.current = target;
    setIndex(target);
    callbacks.current.apply(next);
  };
  const push = async (next: Location) => {
    entries.current[accepted.current] = callbacks.current.snapshot();
    entries.current = entries.current.slice(0, accepted.current + 1);
    entries.current.push(next);
    const target = accepted.current + 1;
    window.history.pushState(
      {
        ...window.history.state,
        productionWorkbench: {
          userId,
          session: session.current,
          index: target,
        },
      },
      "",
      window.location.href,
    );
    native.current = target;
    commit(next, target);
  };
  async function go(next: Location) {
    if (busy.current) return;
    busy.current = true;
    if (await callbacks.current.guard(next)) {
      if (alive.current) await push(next);
      busy.current = false;
    } else if (alive.current)
      setBlocked(() => async () => {
        await push(next);
        busy.current = false;
        setBlocked(null);
      });
  }
  useEffect(() => {
    alive.current = true;
    window.history.replaceState(
      {
        ...window.history.state,
        productionWorkbench: { userId, session: session.current, index: 0 },
      },
      "",
      window.location.href,
    );
    const pop = async (e: PopStateEvent) => {
      const state = e.state?.productionWorkbench;
      if (
        state?.userId !== userId ||
        state.session !== session.current ||
        !entries.current[state.index]
      )
        return;
      native.current = state.index;
      if (travel.current) {
        if (state.index === travel.current.target) {
          const finish = travel.current.finish;
          travel.current = null;
          finish();
        } else window.history.go(travel.current.target - state.index);
        return;
      }
      if (busy.current) {
        await move(accepted.current);
        return;
      }
      busy.current = true;
      const target = state.index,
        next = entries.current[target];
      entries.current[accepted.current] = callbacks.current.snapshot();
      await move(accepted.current);
      if (!alive.current) return;
      const accept = async () => {
        await move(target);
        if (!alive.current) return;
        commit(next, target);
        busy.current = false;
        setBlocked(null);
      };
      if (await callbacks.current.guard(next)) await accept();
      else if (alive.current) setBlocked(() => accept);
    };
    window.addEventListener("popstate", pop);
    return () => {
      alive.current = false;
      window.removeEventListener("popstate", pop);
    };
  }, [userId]);
  return {
    index,
    blocked: !!blocked,
    go,
    back: () => {
      if (!busy.current && accepted.current > 0) window.history.back();
    },
    stay: () => {
      setBlocked(null);
      busy.current = false;
    },
    leave: () => {
      if (blocked) void blocked();
    },
  };
}
