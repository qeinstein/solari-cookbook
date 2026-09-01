import type { TimeEvent, ViolationSnapshot } from "./types";

export const eventLabels: Record<string, string> = {
  invoice_created: "Invoice created",
  customer_payment: "Customer paid",
  payment_webhook: "Payment webhook",
  dispute_opened: "Dispute opened",
  dispute_webhook: "Dispute webhook",
  agent_wakeup: "Agent wakeup",
};

export const branchEventLabels: Record<string, string> = {
  invoice_created: "Invoice",
  customer_payment: "Paid",
  payment_webhook: "Pay sync",
  dispute_opened: "Dispute",
  dispute_webhook: "Dispute sync",
  agent_wakeup: "Wake",
};

export function eventLabel(kind: string) {
  return eventLabels[kind] ?? kind.replaceAll("_", " ");
}

export function branchEventLabel(event: TimeEvent) {
  return branchEventLabels[event.kind] ?? eventLabel(event.kind);
}

export function formatMoment(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function shortHash(value?: string) {
  return value ? value.slice(0, 12) : "not recorded";
}

export function failureLabel(mode: ViolationSnapshot["type"]) {
  return mode === "active_dispute_contact" ? "Dispute contact" : "Paid contact";
}

export function percent(value?: number) {
  return value === undefined ? "—" : `${Math.round(value * 100)}%`;
}
