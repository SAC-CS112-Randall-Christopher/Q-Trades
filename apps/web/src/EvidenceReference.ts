export type EvidenceReference = {
  archive: "full" | "compact";
  episode: string;
  record_id: number;
  sha256: string;
};
