import type { ProjectRetroItem } from "./api/workbench";

export type RetroDraftState = {
  performance_rating: string;
  summary: string;
  wins_text: string;
  gaps_text: string;
  next_focus: string;
};

export function buildRetroDraft(retro: ProjectRetroItem | null | undefined): RetroDraftState {
  if (!retro) {
    return {
      performance_rating: "",
      summary: "",
      wins_text: "",
      gaps_text: "",
      next_focus: "",
    };
  }

  return {
    performance_rating: String(retro.performance_rating),
    summary: retro.summary,
    wins_text: retro.wins.join("\n"),
    gaps_text: retro.gaps.join("\n"),
    next_focus: retro.next_focus,
  };
}
