import { useCallback, useEffect, useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";

interface Confirmation {
  message: string;
  title: string;
  confirmLabel: string;
}
export type Confirm = (
  message: string,
  title?: string,
  confirmLabel?: string,
) => Promise<boolean>;

function ConfirmDialog({
  request,
  finish,
}: {
  request: Confirmation;
  finish: (accepted: boolean) => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const buttons = () =>
      dialog.current?.querySelectorAll<HTMLButtonElement>(
        "button:not([disabled])",
      );
    buttons()?.[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
        return;
      }
      if (event.key !== "Tab") return;
      const elements = buttons();
      if (!elements?.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [finish]);
  return (
    <div className="dialog-backdrop">
      <div
        ref={dialog}
        className="confirmation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirmation-title"
        aria-describedby="confirmation-description"
      >
        <div className="dialog-symbol">
          <ShieldCheck size={24} strokeWidth={1.7} />
        </div>
        <h2 id="confirmation-title">{request.title}</h2>
        <p id="confirmation-description">{request.message}</p>
        <div className="dialog-actions">
          <button className="button secondary" onClick={() => finish(false)}>
            取消
          </button>
          <button className="button primary" onClick={() => finish(true)}>
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function useConfirmation() {
  const [request, setRequest] = useState<Confirmation | null>(null);
  const pending = useRef<{
    resolve: (accepted: boolean) => void;
    focus: HTMLElement | null;
  } | null>(null);
  const confirm: Confirm = useCallback(
    (
      message: string,
      title = "确认离开当前草稿？",
      confirmLabel = "放弃修改并继续",
    ) => {
      // A second action cannot replace the pending decision or share its approval.
      if (pending.current) return Promise.resolve(false);
      return new Promise<boolean>((resolve) => {
        pending.current = {
          resolve,
          focus:
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null,
        };
        setRequest({ message, title, confirmLabel });
      });
    },
    [],
  );
  const finish = useCallback((accepted: boolean) => {
    const current = pending.current;
    if (!current) return;
    pending.current = null;
    setRequest(null);
    current.resolve(accepted);
    requestAnimationFrame(() => {
      if (current.focus?.isConnected) current.focus.focus();
      else document.getElementById("main-content")?.focus();
    });
  }, []);
  useEffect(
    () => () => {
      pending.current?.resolve(false);
      pending.current = null;
    },
    [],
  );
  return {
    confirm,
    confirming: Boolean(request),
    dialog: request ? (
      <ConfirmDialog request={request} finish={finish} />
    ) : null,
  };
}
