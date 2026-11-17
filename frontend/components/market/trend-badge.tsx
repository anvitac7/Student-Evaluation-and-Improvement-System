import { Badge } from "@/components/ui/badge";
import type { TrendClassification } from "@/types/market-analytics";

const TREND_CONFIG: Record<
  Exclude<TrendClassification, null>,
  { label: string; variant: "success" | "destructive" | "secondary" | "default" }
> = {
  rising: { label: "Rising ↑", variant: "success" },
  declining: { label: "Declining ↓", variant: "destructive" },
  stable: { label: "Stable →", variant: "secondary" },
  emerging: { label: "Emerging ✦", variant: "default" },
};

/**
 * Badge for the backend trend classification. A null classification means the
 * backend had no comparable previous period — displayed as "N/A", never as a
 * misleading zero-growth trend.
 */
export function TrendBadge({ trend }: { trend: TrendClassification | null }) {
  if (!trend) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        N/A
      </Badge>
    );
  }
  const config = TREND_CONFIG[trend];
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
