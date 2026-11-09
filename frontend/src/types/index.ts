export interface User {
  id: string;
  email: string;
  name: string;
  picture: string;
}

export interface AuthConfig {
  google: boolean;
  dev: boolean;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ReplicationMode = "auto" | "full" | "single_page";
export type OutputTarget = "static" | "react" | "nextjs" | "wordpress_theme" | "wordpress_headless" | "figma";

export interface ExportRecord {
  target: OutputTarget;
  label: string;
  zip: string;
  size: number;
  info: Record<string, unknown>;
  error: string;
}

export interface QualityPage {
  url: string;
  output_path: string;
  title: string;
  score: number | null;
  grade: string;
  viewports: Record<string, number>;
  issues: string[];
  fixes_applied: number;
}

export interface QualityReport {
  overall_score: number | null;
  grade: string;
  pages: QualityPage[];
  external_refs_removed: number;
  external_refs_remaining: number;
  assets_failed: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  url: string;
  status: JobStatus;
  created_at: number;
  updated_at: number;
  pages_count: number;
  assets_count: number;
  assets_bytes: number;
  avg_ssim: number | null;
  error: string;
}

export interface PageRecord {
  url: string;
  title: string;
  depth: number;
  output_path: string;
  status: string;
  html_bytes: number;
  screenshots: Record<string, string>;
  error: string;
}

export interface AssetRecord {
  url: string;
  category: string;
  ext: string;
  local_path: string;
  status: string;
  size: number;
  content_type: string;
  source_page: string;
  error: string;
}

export interface CompareRecord {
  page_url: string;
  viewport: string;
  ssim: number;
  diff_ratio: number;
  original_png: string;
  generated_png: string;
  diff_png: string;
  width: number;
  height_original: number;
  height_generated: number;
  issues: string[];
}

export interface Analysis {
  frameworks?: string[];
  palette?: string[];
  fonts?: string[];
  components?: string[];
  interactions?: Record<string, number>;
  pages?: unknown[];
  [k: string]: unknown;
}

export interface ProjectDetail extends ProjectSummary {
  options: Record<string, unknown>;
  pages: PageRecord[];
  assets: AssetRecord[];
  comparisons: CompareRecord[];
  analysis: Analysis;
  has_zip: boolean;
  duration: number;
  exports?: ExportRecord[];
  quality?: QualityReport;
  is_running?: boolean;
}

export interface DashboardStats {
  projects_total: number;
  projects_completed: number;
  projects_running: number;
  pages_total: number;
  assets_total: number;
  assets_bytes: number;
  recent: ProjectSummary[];
}

export interface ProgressEvent {
  job_id: string;
  phase: string;
  message: string;
  progress: number;
  level: "info" | "warn" | "error" | "success";
  data: Record<string, unknown>;
  ts: number;
}

export interface ReplicationRequest {
  url: string;
  name?: string;
  mode: ReplicationMode;
  max_depth?: number;
  max_pages?: number;
  viewports?: string[];
  fix_cycles?: number;
  keep_js?: boolean;
  run_quality_check?: boolean;
  outputs?: OutputTarget[];
  keep_external_links?: boolean;
  import_wp_content?: boolean;
}
