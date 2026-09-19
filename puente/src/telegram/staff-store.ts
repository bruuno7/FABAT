import type { StaffRole } from "../lib/contract.js";

export type StaffClaim = {
  chat_id: string;
  user_id: string;
  role: StaffRole;
  display_name: string;
  claimed_at: string;
};

/** Caché local; HappyRobot/Redis es la autoridad y MANDO queda como fallback legado. */
export function createStaffStore() {
  const byChat = new Map<string, StaffClaim>();
  const byRole = new Map<StaffRole, string>();

  return {
    getByChat(chatId: string) {
      return byChat.get(chatId);
    },
    getByRole(role: StaffRole) {
      const chatId = byRole.get(role);
      return chatId ? byChat.get(chatId) : undefined;
    },
    list() {
      return [...byChat.values()].sort((a, b) =>
        a.role.localeCompare(b.role),
      );
    },
    replaceAll(claims: StaffClaim[]) {
      byChat.clear();
      byRole.clear();
      for (const next of claims) {
        byChat.set(next.chat_id, next);
        byRole.set(next.role, next.chat_id);
      }
    },
    claim(
      next: StaffClaim,
    ):
      | { ok: true; previous?: StaffClaim }
      | { ok: false; reason: "taken"; holder: StaffClaim } {
      const takenBy = byRole.get(next.role);
      if (takenBy && takenBy !== next.chat_id) {
        const holder = byChat.get(takenBy);
        if (holder) return { ok: false, reason: "taken", holder };
      }
      const previous = byChat.get(next.chat_id);
      if (previous && previous.role !== next.role) {
        byRole.delete(previous.role);
      }
      byChat.set(next.chat_id, next);
      byRole.set(next.role, next.chat_id);
      return {
        ok: true,
        previous:
          previous && previous.role !== next.role ? previous : undefined,
      };
    },
    release(chatId: string) {
      const previous = byChat.get(chatId);
      if (!previous) return undefined;
      byChat.delete(chatId);
      if (byRole.get(previous.role) === chatId) byRole.delete(previous.role);
      return previous;
    },
  };
}

export type StaffStore = ReturnType<typeof createStaffStore>;
