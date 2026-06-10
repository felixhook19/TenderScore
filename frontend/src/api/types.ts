export interface LoginResponse {
  challenge_token: string;
  expires_at: string;
  detail: string;
}

export interface SessionResponse {
  session_token: string;
  expires_at: string;
}

export interface Me {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  roles: string[];
  privileges: string[];
}

export interface Procurement {
  id: string;
  title: string;
  reference: string;
  regime: string;
  status: string;
  pinned_model_version: string | null;
  framework_locked_at: string | null;
  framework_lock_hash: string | null;
}

export interface QueueEntry {
  recommendation_id: string;
  run_id: string;
  criterion_id: string;
  criterion_ref: string;
  criterion_title: string;
  bidder_id: string;
  score: number | null;
  confidence_tier: "converged" | "moderate" | "escalate";
  variance: number;
  decided: boolean;
}

export interface Citation {
  span: string;
  start: number;
  end: number;
  supports: string;
  verified?: boolean;
}

export interface Descriptor {
  band: number;
  label: string;
  descriptor_text: string;
}

export interface RecommendationDetail {
  recommendation_id: string;
  criterion_ref: string;
  criterion_title: string;
  score: number | null;
  band_label: string | null;
  justification: string;
  citations: Citation[];
  requirements: { met?: string[]; partial?: string[]; not_met?: string[] };
  weaknesses: string[];
  variance: number;
  confidence_tier: "converged" | "moderate" | "escalate";
  descriptors: Descriptor[];
}

export interface DecisionResponse {
  id: string;
  recommendation_id: string;
  action: "confirm" | "amend";
  final_score: number;
  rationale: string | null;
}
