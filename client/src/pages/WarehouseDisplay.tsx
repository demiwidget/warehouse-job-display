import { useEffect, useState } from "react";
import { useParams } from "wouter";
import { trpc } from "@/lib/trpc";
import { Card } from "@/components/ui/card";
import { AlertCircle, RefreshCw, Clock } from "lucide-react";
import { format } from "date-fns";

export default function WarehouseDisplay() {
  const { areaId } = useParams<{ areaId: string }>();
  const [refreshCount, setRefreshCount] = useState(0);

  const { data: area } = trpc.warehouse.getArea.useQuery(
    { areaId: parseInt(areaId || "0") },
    { enabled: !!areaId }
  );

  const { data: displaySettings } = trpc.warehouse.getDisplaySettings.useQuery(
    { areaId: parseInt(areaId || "0") },
    { enabled: !!areaId }
  );

  const { data: jobMappings } = trpc.warehouse.getAreaJobs.useQuery(
    { areaId: parseInt(areaId || "0") },
    { enabled: !!areaId }
  );

  // Set up auto-refresh
  useEffect(() => {
    if (!displaySettings) return;

    const interval = setInterval(() => {
      setRefreshCount((c) => c + 1);
    }, displaySettings.refreshIntervalSeconds * 1000);

    return () => clearInterval(interval);
  }, [displaySettings]);

  if (!areaId) {
    return (
      <div className="min-h-screen bg-red-900 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="w-16 h-16 text-red-200 mx-auto mb-4" />
          <h1 className="text-4xl font-bold text-white mb-2">Invalid Area</h1>
          <p className="text-red-100">No area ID provided</p>
        </div>
      </div>
    );
  }

  if (!area || !displaySettings) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-full border-4 border-slate-700 border-t-blue-400 animate-spin mx-auto mb-4" />
          <p className="text-slate-300">Loading display...</p>
        </div>
      </div>
    );
  }

  const bgColor = displaySettings.theme === "dark" ? "bg-slate-900" : "bg-white";
  const textColor = displaySettings.theme === "dark" ? "text-white" : "text-slate-900";
  const secondaryTextColor = displaySettings.theme === "dark" ? "text-slate-400" : "text-slate-600";
  const cardBg = displaySettings.theme === "dark" ? "bg-slate-800" : "bg-slate-100";
  const cardBorder = displaySettings.theme === "dark" ? "border-slate-700" : "border-slate-300";

  const fontSizeClass = {
    small: "text-2xl",
    medium: "text-4xl",
    large: "text-6xl",
    xlarge: "text-8xl",
  }[displaySettings.fontSize];

  const jobTitleSize = {
    small: "text-xl",
    medium: "text-3xl",
    large: "text-5xl",
    xlarge: "text-6xl",
  }[displaySettings.fontSize];

  const subtitleSize = {
    small: "text-lg",
    medium: "text-2xl",
    large: "text-4xl",
    xlarge: "text-5xl",
  }[displaySettings.fontSize];

  return (
    <div className={`min-h-screen ${bgColor} p-8 flex flex-col`}>
      {/* Header */}
      <div className="mb-8">
        <h1 className={`${fontSizeClass} font-bold ${textColor} mb-2`}>
          {area.displayName}
        </h1>
        <div className={`flex items-center gap-2 ${secondaryTextColor}`}>
          <Clock className="w-6 h-6" />
          <span className="text-lg">
            Last updated: {format(new Date(), "HH:mm:ss")} (Refresh #{refreshCount})
          </span>
        </div>
      </div>

      {/* Jobs Grid */}
      <div className="flex-1 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 auto-rows-max">
        {jobMappings && jobMappings.length > 0 ? (
          jobMappings.map((mapping) => (
            <JobCard
              key={mapping.id}
              jobNumber={mapping.currentRmsJobNumber}
              jobId={mapping.currentRmsJobId}
              displaySettings={displaySettings}
              cardBg={cardBg}
              cardBorder={cardBorder}
              textColor={textColor}
              secondaryTextColor={secondaryTextColor}
              jobTitleSize={jobTitleSize}
              subtitleSize={subtitleSize}
            />
          ))
        ) : (
          <div
            className={`col-span-full flex items-center justify-center py-16 ${cardBg} border-2 ${cardBorder} rounded-lg`}
          >
            <p className={`${secondaryTextColor} text-2xl`}>No jobs assigned to this area</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className={`mt-8 pt-4 border-t ${cardBorder} flex items-center justify-between`}>
        <div className={`flex items-center gap-2 ${secondaryTextColor}`}>
          <RefreshCw className="w-5 h-5" />
          <span>Refreshing every {displaySettings.refreshIntervalSeconds} seconds</span>
        </div>
        <span className={secondaryTextColor}>Warehouse Job Display System</span>
      </div>
    </div>
  );
}

interface JobCardProps {
  jobNumber: string;
  jobId: string;
  displaySettings: any;
  cardBg: string;
  cardBorder: string;
  textColor: string;
  secondaryTextColor: string;
  jobTitleSize: string;
  subtitleSize: string;
}

function JobCard({
  jobNumber,
  jobId,
  displaySettings,
  cardBg,
  cardBorder,
  textColor,
  secondaryTextColor,
  jobTitleSize,
  subtitleSize,
}: JobCardProps) {
  const { data: jobDetails, isLoading } = trpc.warehouse.getJobDetails.useQuery(
    { jobId },
    { refetchInterval: displaySettings.refreshIntervalSeconds * 1000 }
  );

  if (isLoading) {
    return (
      <Card className={`p-8 border-2 ${cardBg} ${cardBorder} flex items-center justify-center`}>
        <div className="w-8 h-8 rounded-full border-4 border-slate-700 border-t-blue-400 animate-spin" />
      </Card>
    );
  }

  return (
    <Card className={`p-8 border-4 border-blue-500 ${cardBg} ${cardBorder} hover:border-blue-400 transition-colors`}>
      <div className="space-y-6">
        {/* Job Number */}
        {displaySettings.showJobNumber && (
          <div>
            <p className={`${secondaryTextColor} text-sm font-semibold mb-2`}>JOB NUMBER</p>
            <p className={`${jobTitleSize} font-bold ${textColor}`}>{jobNumber}</p>
          </div>
        )}

        {/* Job Title */}
        {displaySettings.showJobTitle && jobDetails?.jobTitle && (
          <div>
            <p className={`${secondaryTextColor} text-sm font-semibold mb-2`}>JOB TITLE</p>
            <p className={`${subtitleSize} font-semibold ${textColor} line-clamp-2`}>
              {jobDetails.jobTitle}
            </p>
          </div>
        )}

        {/* Load Date & Time */}
        {displaySettings.showLoadTime && jobDetails?.loadDate && (
          <div className="pt-4 border-t border-slate-700">
            <p className={`${secondaryTextColor} text-sm font-semibold mb-2`}>LOAD DATE & TIME</p>
            <div className="space-y-2">
              <p className={`${jobTitleSize} font-bold ${textColor}`}>
                {format(new Date(jobDetails.loadDate), "MMM dd")}
              </p>
              {jobDetails.loadTime && (
                <p className={`${subtitleSize} font-semibold ${textColor}`}>
                  {jobDetails.loadTime}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Status */}
        {jobDetails?.status && (
          <div className="pt-4">
            <span
              className={`inline-block px-4 py-2 rounded-full text-sm font-semibold ${
                jobDetails.status === "completed"
                  ? "bg-green-500/20 text-green-300"
                  : "bg-blue-500/20 text-blue-300"
              }`}
            >
              {jobDetails.status}
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}
