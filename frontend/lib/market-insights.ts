/**
 * Derived market insights for the TPO Market Insights dashboard (Phase 5).
 *
 * IMPORTANT — every number used here is backend-supplied (Phase 3
 * `trending_skills` / `historical_trends` / `emerging_skills` /
 * `job_families` / `companies`). These helpers never re-derive percentages
 * from raw counts and never invent classifications:
 *
 * - Trend classifications (rising / declining / stable / emerging) always
 *   come from the backend's `trend` field.
 * - Growth values always come from the backend's `yoy_growth_pct` fields,
 *   which are only computed between COMPARABLE windows (Jan-Oct pair for the
 *   dataset's partial latest year, full years otherwise). A `null` growth
 *   means "no comparable previous period" and is never treated as zero.
 *
 * The only NEW logic here is presentation-level ranking/classification of
 * what the backend already measured. Its formulas are documented on each
 * export and are deterministic (stable tie-breaking by skill name).
 */

import type {
  CompanyMarketAnalytics,
  EmergingSkill,
  HistoricalSkillTrend,
  JobFamilyMarketAnalytics,
  MarketMeta,
  TrendClassification,
  TrendingSkill,
} from "@/types/market-analytics";

/** A skill's latest comparable YoY growth is >= +25% ("significant growth").
 * Deliberately stricter than the backend's "rising" boundary of +10%. */
export const FAST_GROWTH_THRESHOLD_PCT = 25;

/** A group-unique skill is flagged "rare market-wide" when it is required by
 * fewer than 5% of the filtered postings. */
export const RARE_MARKET_WIDE_THRESHOLD = 0.05;

/** Classification labels for the emerging/insights section. */
export type EmergingClass =
  | "newly-emerging"
  | "fast-growing"
  | "consistently-growing"
  | "recently-accelerating"
  | "rising"
  | "stable"
  | "insufficient-data";

export interface EmergingSeriesPoint {
  year: number;
  /** Backend demand share for that year. */
  demandPct: number;
  /** Backend posting count for that year. */
  postingCount: number;
  /** Backend growth between comparable windows ending at that year. */
  yoyGrowthPct: number | null;
}

export interface EmergingCandidate {
  slug: string;
  name: string;
  category: string | null;
  /** The backend listed this skill in `emerging_skills`. */
  isEmerging: boolean;
  classification: EmergingClass;
  /** Postings in the latest comparable window (backend). */
  currentCount: number;
  /** Postings in the previous comparable window (backend). */
  previousCount: number;
  /** Latest comparable YoY growth (backend; null = not comparable). */
  growthPct: number | null;
  /** Backend trend classification. */
  trend: TrendClassification | null;
  /** Demand % of the current window (backend; emerging skills only). */
  currentWindowDemandPct: number | null;
  /** Overall demand within the filtered range (backend; trending list only). */
  overallDemandPct: number | null;
  /** Year-wise demand trajectory (backend historical_trends). */
  series: EmergingSeriesPoint[];
}

function growthSeries(history: HistoricalSkillTrend | undefined): EmergingSeriesPoint[] {
  return (history?.years ?? []).map((year) => ({
    year: year.year,
    demandPct: year.demand_pct,
    postingCount: year.posting_count,
    yoyGrowthPct: year.yoy_growth_pct,
  }));
}

/**
 * Classify ONE candidate skill. Rules (evaluated top-down, first match wins):
 *
 * 1. newly-emerging — the backend classified the skill `emerging`, which it
 *    only does when the previous comparable window HAD postings in the
 *    filtered population (previous == 0, current > 0, comparable). Missing or
 *    filter-excluded previous periods therefore never produce this label.
 * 2. insufficient-data — the backend's latest comparable growth is null.
 * 3. fast-growing — latest comparable growth >= +25%.
 * 4. consistently-growing — the skill's historical series has at least 2
 *    comparable period-over-period growth values (backend) and every one of
 *    them is > 0 (the 1st dataset year has no comparable predecessor, so its
 *    null growth is simply skipped, not read as zero).
 * 5. recently-accelerating — the latest two comparable growth values both
 *    exist and the latest is strictly greater than the preceding one.
 * 6. rising — backend classification `rising` (growth >= +10%, not fast).
 * 7. stable — otherwise (remaining candidates all have positive growth
 *    below +10%, which the backend classifies as stable).
 */
export function classifyEmergingCandidate(
  isEmerging: boolean,
  trend: TrendClassification | null,
  growthPct: number | null,
  series: EmergingSeriesPoint[]
): EmergingClass {
  if (isEmerging && trend === "emerging") return "newly-emerging";
  if (growthPct == null) return "insufficient-data";
  if (growthPct >= FAST_GROWTH_THRESHOLD_PCT) return "fast-growing";
  const growths = series
    .map((point) => point.yoyGrowthPct)
    .filter((value): value is number => value != null);
  if (growths.length >= 2 && growths.every((value) => value > 0)) {
    return "consistently-growing";
  }
  const latest = growths[growths.length - 1];
  const preceding = growths[growths.length - 2];
  if (latest != null && preceding != null && latest > preceding) {
    return "recently-accelerating";
  }
  if (trend === "rising") return "rising";
  return "stable";
}

/**
 * Candidate pool for the emerging/insights section = the backend's
 * `emerging_skills` plus every trending skill with positive comparable
 * growth, joined with `historical_trends` for trajectories. Skills whose
 * latest growth is null (no comparable previous period) and that are not
 * emerging are excluded — no invented classifications.
 */
export function buildEmergingCandidates(
  trending: TrendingSkill[],
  emerging: EmergingSkill[],
  historical: HistoricalSkillTrend[]
): EmergingCandidate[] {
  const emergingBySlug = new Map(emerging.map((skill) => [skill.slug, skill]));
  const historyBySlug = new Map(historical.map((entry) => [entry.slug, entry]));

  const candidates: EmergingCandidate[] = [];
  const seen = new Set<string>();

  const addCandidate = (skill: TrendingSkill) => {
    if (seen.has(skill.slug)) return;
    seen.add(skill.slug);
    const emergingRecord = emergingBySlug.get(skill.slug);
    const isEmerging = emergingRecord != null;
    if (!isEmerging && !(skill.yoy_growth_pct != null && skill.yoy_growth_pct > 0)) {
      return; // neither emerging nor positive comparable growth
    }
    const series = growthSeries(historyBySlug.get(skill.slug));
    candidates.push({
      slug: skill.slug,
      name: skill.name,
      category: skill.category,
      isEmerging,
      classification: classifyEmergingCandidate(
        isEmerging,
        skill.trend,
        skill.yoy_growth_pct,
        series
      ),
      currentCount: skill.current_period_count,
      previousCount: skill.previous_period_count,
      growthPct: skill.yoy_growth_pct,
      trend: skill.trend,
      currentWindowDemandPct: emergingRecord?.current_period_demand_pct ?? null,
      overallDemandPct: skill.demand_pct,
      series,
    });
  };

  // Emerging skills first so they are listed even when they fall outside the
  // backend's trending limit; trending records carry the richer fields.
  for (const emergingRecord of emerging) {
    const trendingRecord = trending.find((skill) => skill.slug === emergingRecord.slug);
    if (trendingRecord != null) {
      addCandidate(trendingRecord);
      continue;
    }
    // Emerging skill outside the trending limit — synthesise the display
    // record purely from backend fields (emerging + historical). Its growth
    // is null by the backend's own rule (previous window count is 0).
    const series = growthSeries(historyBySlug.get(emergingRecord.slug));
    candidates.push({
      slug: emergingRecord.slug,
      name: emergingRecord.name,
      category: emergingRecord.category,
      isEmerging: true,
      classification: "newly-emerging",
      currentCount: emergingRecord.current_period_count,
      previousCount: emergingRecord.previous_period_count,
      growthPct: null,
      trend: "emerging",
      currentWindowDemandPct: emergingRecord.current_period_demand_pct,
      overallDemandPct: null,
      series,
    });
  }
  for (const skill of trending) addCandidate(skill);
  return candidates;
}

/** Summary figures for the emerging/insights section (all backend values). */
export interface EmergingSummary {
  /** Skills in the backend's emerging list. */
  emergingCount: number;
  /** Candidates classified "fast-growing" (>= +25% latest comparable growth). */
  fastGrowingCount: number;
  /** Highest current-window demand % among emerging skills, or null. */
  highestEmergingDemandPct: number | null;
  /** Strongest latest comparable growth among candidates, or null. */
  strongestGrowthPct: number | null;
  strongestGrowthName: string | null;
}

export function summarizeEmerging(
  emerging: EmergingSkill[],
  candidates: EmergingCandidate[]
): EmergingSummary {
  let highestEmergingDemandPct: number | null = null;
  for (const skill of emerging) {
    if (highestEmergingDemandPct == null || skill.current_period_demand_pct > highestEmergingDemandPct) {
      highestEmergingDemandPct = skill.current_period_demand_pct;
    }
  }
  let strongestGrowthPct: number | null = null;
  let strongestGrowthName: string | null = null;
  for (const candidate of candidates) {
    const growth = candidate.growthPct;
    if (growth == null) continue;
    if (
      strongestGrowthPct == null ||
      growth > strongestGrowthPct ||
      (growth === strongestGrowthPct && candidate.name < (strongestGrowthName ?? ""))
    ) {
      strongestGrowthPct = growth;
      strongestGrowthName = candidate.name;
    }
  }
  return {
    emergingCount: emerging.length,
    fastGrowingCount: candidates.filter(
      (candidate) => candidate.classification === "fast-growing"
    ).length,
    highestEmergingDemandPct,
    strongestGrowthPct,
    strongestGrowthName,
  };
}

/** Deterministic ranking: by current-window postings or by latest growth. */
export type EmergingRanking = "demand" | "growth";

export function rankEmergingCandidates(
  candidates: EmergingCandidate[],
  ranking: EmergingRanking
): EmergingCandidate[] {
  const sorted = [...candidates];
  if (ranking === "growth") {
    sorted.sort(
      (a, b) =>
        (b.growthPct ?? Number.NEGATIVE_INFINITY) -
          (a.growthPct ?? Number.NEGATIVE_INFINITY) ||
        a.name.localeCompare(b.name)
    );
  } else {
    sorted.sort(
      (a, b) => b.currentCount - a.currentCount || a.name.localeCompare(b.name)
    );
  }
  return sorted;
}

/** Signed growth formatter ("+12.5%", "-3%", never used for null values). */
export function formatSignedGrowth(value: number): string {
  return `${value > 0 ? "+" : ""}${value}%`;
}

/**
 * Short explanation of a skill's backend trend classification. Uses only
 * backend fields; the ±10% stable range mirrors the backend's thresholds.
 */
export function trendExplanation(skill: TrendingSkill): string {
  if (skill.trend == null || skill.yoy_growth_pct == null) {
    return "No comparable previous-period demand was available for this skill.";
  }
  switch (skill.trend) {
    case "emerging":
      return "The skill appeared in the current period but not in the comparable previous period.";
    case "rising":
      return `Demand increased by ${skill.yoy_growth_pct}% compared with the previous comparable period.`;
    case "declining":
      return `Demand decreased by ${Math.abs(skill.yoy_growth_pct)}% compared with the previous comparable period.`;
    case "stable":
      return "Demand stayed within the stable range (within ±10% of the previous comparable period).";
  }
}

export interface TrendObservationInput {
  skills: TrendingSkill[];
  historical: HistoricalSkillTrend[];
  families: JobFamilyMarketAnalytics[];
  companies: CompanyMarketAnalytics[];
  meta: MarketMeta | undefined;
}

/**
 * Deterministic market observations for the trending-skills section.
 *
 * Formulas (all values backend-supplied; ties broken by skill name; lists
 * capped at 5 names with an "and N more" suffix):
 *
 * 1. Strongest comparable growth — max `yoy_growth_pct` among the listed
 *    trending skills (null growths ignored).
 * 2. Highest demand — max `posting_count` among the listed trending skills.
 * 3. Sustained growth — over ALL `historical_trends` (not just the trending
 *    list): at least 2 non-null comparable growth values and every one > 0.
 * 4. Losing demand — backend classification `declining` among trending skills.
 * 5. Stable demand — backend classification `stable` among trending skills.
 * 6. Multi-family reach — skills required by >= 2 job families, counted
 *    among each family's TOP SKILLS (the API supplies the top 10 per family).
 * 7. Company concentration — for a skill, max posting_count that any single
 *    company's top-skills list reports, divided by the skill's total postings
 *    across the filtered years (sum of its historical yearly counts); shown
 *    when >= 50% and at least two companies are present. Counts only the
 *    companies whose top-skills list includes the skill.
 *
 * An observation is omitted entirely when its evidence is unavailable —
 * nothing is stated from zero-filled or missing data.
 */
export function buildTrendObservations(input: TrendObservationInput): string[] {
  const { skills, historical, families, companies, meta } = input;
  const observations: string[] = [];
  if (skills.length === 0) return observations;

  // 1. Strongest comparable growth.
  const withGrowth = skills.filter((skill) => skill.yoy_growth_pct != null);
  if (withGrowth.length > 0 && meta?.current_period && meta.previous_period) {
    const best = [...withGrowth].sort(
      (a, b) =>
        (b.yoy_growth_pct ?? 0) - (a.yoy_growth_pct ?? 0) ||
        a.name.localeCompare(b.name)
    )[0];
    if (best) {
      observations.push(
        `${best.name} shows the strongest comparable growth: ${formatSignedGrowth(best.yoy_growth_pct ?? 0)} between ${meta.previous_period.label} and ${meta.current_period.label}.`
      );
    }
  }

  // 2. Highest demand among the listed trending skills.
  const highest = [...skills].sort(
    (a, b) => b.posting_count - a.posting_count || a.name.localeCompare(b.name)
  )[0];
  if (highest) {
    observations.push(
      `${highest.name} has the highest overall demand: ${highest.posting_count} posting${highest.posting_count === 1 ? "" : "s"} (${highest.demand_pct}% of the filtered postings).`
    );
  }

  // 3. Sustained growth across all comparable periods (every in-scope skill).
  const sustained = historical
    .map((entry) => {
      const growths = entry.years
        .map((year) => year.yoy_growth_pct)
        .filter((value): value is number => value != null);
      return { name: entry.name, growths };
    })
    .filter(
      (entry) =>
        entry.growths.length >= 2 && entry.growths.every((value) => value > 0)
    )
    .sort((a, b) => {
      const latestA = a.growths[a.growths.length - 1] ?? 0;
      const latestB = b.growths[b.growths.length - 1] ?? 0;
      return latestB - latestA || a.name.localeCompare(b.name);
    });
  if (sustained.length > 0) {
    observations.push(
      `${formatNameList(sustained.map((entry) => entry.name))} grew in every comparable period available under the current filters.`
    );
  }

  // 4. Losing demand (backend classification).
  const declining = skills.filter((skill) => skill.trend === "declining");
  if (declining.length > 0) {
    observations.push(
      `${formatNameList(declining.map((skill) => skill.name))} ${declining.length === 1 ? "is" : "are"} losing demand compared with the previous comparable period.`
    );
  }

  // 5. Stable demand (backend classification; ±10% band).
  const stable = skills.filter((skill) => skill.trend === "stable");
  if (stable.length > 0) {
    observations.push(
      `${stable.length} skill${stable.length === 1 ? "" : "s"} held stable demand (within ±10% of the previous comparable period), including ${formatNameList(stable.map((skill) => skill.name), 4)}.`
    );
  }

  // 6. Skills demanded across multiple job families (per-family top skills).
  if (families.length > 0) {
    const familyReach = historical
      .map((entry) => ({
        name: entry.name,
        familyCount: families.filter((family) =>
          family.top_skills.some((skill) => skill.slug === entry.slug)
        ).length,
      }))
      .filter((entry) => entry.familyCount >= 2)
      .sort(
        (a, b) =>
          b.familyCount - a.familyCount || a.name.localeCompare(b.name)
      );
    if (familyReach.length > 0) {
      observations.push(
        `Skills demanded across multiple job families (counted among each family's top skills): ${familyReach
          .slice(0, 5)
          .map((entry) => `${entry.name} (${entry.familyCount} of ${families.length} families)`)
          .join(", ")}${familyReach.length > 5 ? `, and ${familyReach.length - 5} more` : ""}.`
      );
    }
  }

  // 7. Demand concentrated in a single company (per-company top skills).
  if (companies.length >= 2) {
    const concentrations = historical
      .map((entry) => {
        const totalPostings = entry.years.reduce(
          (sum, year) => sum + year.posting_count,
          0
        );
        let best: { company: string; count: number } | null = null;
        for (const company of companies) {
          const count = company.top_skills.find(
            (skill) => skill.slug === entry.slug
          )?.posting_count;
          if (count != null && (best == null || count > best.count)) {
            best = { company: company.company_name, count };
          }
        }
        if (best == null || totalPostings === 0) return null;
        const share = best.count / totalPostings;
        return share >= 0.5
          ? {
              name: entry.name,
              company: best.company,
              count: best.count,
              total: totalPostings,
              share,
            }
          : null;
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry != null)
      .sort((a, b) => b.share - a.share || a.name.localeCompare(b.name));
    if (concentrations.length > 0) {
      const top = concentrations[0];
      if (top) {
        observations.push(
          `Demand for ${top.name} is concentrated in ${top.company}: ${top.count} of its ${top.total} filtered postings (counted among each company's top skills).`
        );
      }
    }
  }

  return observations;
}

/** "A", "A and B", "A, B, C and D" — capped with an "and N more" suffix. */
function formatNameList(names: string[], cap = 5): string {
  if (names.length === 0) return "";
  const shown = names.slice(0, cap);
  const remainder = names.length - shown.length;
  const last = shown[shown.length - 1];
  const first = shown[0];
  if (last == null || first == null) return "";
  const head =
    shown.length === 1 ? first : `${shown.slice(0, -1).join(", ")} and ${last}`;
  return remainder > 0 ? `${head} (and ${remainder} more)` : head;
}

// ---------------------------------------------------------------------------
// Entity-comparison derivations (Phase 5) — company or job-family selections
// ---------------------------------------------------------------------------

export interface MatrixCell {
  /** Backend demand % within that entity's own postings. */
  demandPct: number;
  /** Backend posting count within that entity. */
  postingCount: number;
}

export interface MatrixRow {
  slug: string;
  name: string;
  /** One cell per compared entity (same order as the entities array). */
  cells: Array<MatrixCell | null>;
  /** Highest demand % across the selected entities (for row ordering). */
  maxDemandPct: number;
}

/**
 * Skill-demand matrix rows across the compared entities. The union of skills
 * required by at least one entity; a cell is null when the entity does not
 * require the skill (a genuine "not required", not missing data). Sorted by
 * the entity's own backend demand percentages, ties by skill name.
 */
export function buildComparisonMatrix(
  entities: Array<{ skills: TrendingSkill[] }>
): MatrixRow[] {
  const bySlug: Array<Map<string, TrendingSkill>> = entities.map((entity) => {
    const map = new Map<string, TrendingSkill>();
    for (const skill of entity.skills) map.set(skill.slug, skill);
    return map;
  });
  const union = new Map<string, string>();
  for (const map of bySlug) {
    for (const [slug, skill] of map) {
      if (!union.has(slug)) union.set(slug, skill.name);
    }
  }
  const rows: MatrixRow[] = [];
  for (const [slug, name] of union) {
    const cells = bySlug.map((map) => {
      const skill = map.get(slug);
      return skill ? { demandPct: skill.demand_pct, postingCount: skill.posting_count } : null;
    });
    const maxDemandPct = cells.reduce(
      (max, cell) => Math.max(max, cell?.demandPct ?? 0),
      0
    );
    rows.push({ slug, name, cells, maxDemandPct });
  }
  rows.sort((a, b) => b.maxDemandPct - a.maxDemandPct || a.name.localeCompare(b.name));
  return rows;
}

export interface SharedSkill {
  slug: string;
  name: string;
  /** Number of compared entities requiring the skill. */
  entityCount: number;
  /** Per requiring entity: label, backend count and backend demand %. */
  requiring: Array<{ key: string; label: string; postingCount: number; demandPct: number }>;
}

/** Skills required by >= 2 of the compared entities ("multiple selected companies"). */
export function buildSharedSkills(
  entities: Array<{ entity_key: string; entity_label: string; skills: TrendingSkill[] }>
): SharedSkill[] {
  const result: SharedSkill[] = [];
  const all = new Map<string, string>();
  for (const entity of entities) {
    for (const skill of entity.skills) {
      if (!all.has(skill.slug)) all.set(skill.slug, skill.name);
    }
  }
  for (const [slug, name] of all) {
    const requiring = entities
      .filter((entity) => entity.skills.some((skill) => skill.slug === slug))
      .map((entity) => {
        const skill = entity.skills.find((entry) => entry.slug === slug);
        return {
          key: entity.entity_key,
          label: entity.entity_label,
          postingCount: skill?.posting_count ?? 0,
          demandPct: skill?.demand_pct ?? 0,
        };
      });
    if (requiring.length >= 2) {
      result.push({ slug, name, entityCount: requiring.length, requiring });
    }
  }
  result.sort(
    (a, b) =>
      b.entityCount - a.entityCount ||
      b.requiring.reduce((sum, r) => sum + r.postingCount, 0) -
        a.requiring.reduce((sum, r) => sum + r.postingCount, 0) ||
      a.name.localeCompare(b.name)
  );
  return result;
}

export interface UniqueSkill {
  slug: string;
  name: string;
  postingCount: number;
  demandPct: number;
  /** Total postings requiring the skill across the filtered years (backend
   * historical counts) — used to flag skills that are rare market-wide. */
  overallPostingCount: number | null;
}

export interface UniqueSkillGroup {
  entityKey: string;
  entityLabel: string;
  skills: UniqueSkill[];
}

/**
 * Skills required by exactly ONE of the compared entities — genuinely
 * specific within the selected group. `overallPostingCount` (backend yearly
 * counts summed across the filtered years) lets the UI distinguish a skill
 * that is also rare in the overall filtered market.
 */
export function buildUniqueSkills(
  entities: Array<{ entity_key: string; entity_label: string; skills: TrendingSkill[] }>,
  overallPostingCount: Map<string, number>
): UniqueSkillGroup[] {
  const groups: UniqueSkillGroup[] = [];
  const all = new Map<string, string>();
  for (const entity of entities) {
    for (const skill of entity.skills) {
      if (!all.has(skill.slug)) all.set(skill.slug, skill.name);
    }
  }
  for (const entity of entities) {
    const skills: UniqueSkill[] = [];
    for (const skill of entity.skills) {
      const requiredByOthers = entities.some(
        (other) =>
          other.entity_key !== entity.entity_key &&
          other.skills.some((entry) => entry.slug === skill.slug)
      );
      if (!requiredByOthers) {
        skills.push({
          slug: skill.slug,
          name: skill.name,
          postingCount: skill.posting_count,
          demandPct: skill.demand_pct,
          overallPostingCount: overallPostingCount.get(skill.slug) ?? null,
        });
      }
    }
    skills.sort((a, b) => b.postingCount - a.postingCount || a.name.localeCompare(b.name));
    if (skills.length > 0) {
      groups.push({
        entityKey: entity.entity_key,
        entityLabel: entity.entity_label,
        skills,
      });
    }
  }
  return groups;
}

export function isRareMarketWide(
  overallPostingCount: number | null,
  totalPostings: number
): boolean {
  return (
    overallPostingCount != null &&
    totalPostings > 0 &&
    overallPostingCount / totalPostings < RARE_MARKET_WIDE_THRESHOLD
  );
}
