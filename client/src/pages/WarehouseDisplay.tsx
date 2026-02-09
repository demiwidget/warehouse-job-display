import { useEffect, useState } from "react";
import { useParams } from "wouter";
import { trpc } from "@/lib/trpc";
import { AlertCircle, RefreshCw, Clock } from "lucide-react";
import { format } from "date-fns";

export default function WarehouseDisplay() {
  const { areaId } = useParams<{ areaId: string }>();
  const [refreshCount, setRefreshCount] = useState(0);

  // Parse areaId safely, converting to number and validating it's not NaN
  const parsedAreaId = areaId ? parseInt(areaId, 10) : null;
  const isValidAreaId = parsedAreaId !== null && !isNaN(parsedAreaId) && parsedAreaId > 0;

  const { data: area } = trpc.warehouse.getArea.useQuery(
    { areaId: parsedAreaId || 0 },
    { enabled: isValidAreaId }
  );

  const { data: displaySettings } = trpc.warehouse.getDisplaySettings.useQuery(
    { areaId: parsedAreaId || 0 },
    { enabled: isValidAreaId }
  );

  const { data: jobMappings } = trpc.warehouse.getAreaJobs.useQuery(
    { areaId: parsedAreaId || 0 },
    { enabled: isValidAreaId }
  );

  // Set up auto-refresh
  useEffect(() => {
    if (!displaySettings) return;

    const interval = setInterval(() => {
      setRefreshCount((c) => c + 1);
    }, displaySettings.refreshIntervalSeconds * 1000);

    return () => clearInterval(interval);
  }, [displaySettings]);

  if (!isValidAreaId) {
    return (
      <div className="min-h-screen bg-red-900 flex items-center justify-center p-8">
        <div className="text-center">
          <AlertCircle className="w-32 h-32 text-red-200 mx-auto mb-8" />
          <h1 className="text-8xl font-bold text-white mb-4">Invalid Area</h1>
          <p className="text-4xl text-red-100">No valid area ID provided</p>
        </div>
      </div>
    );
  }

  if (!area || !displaySettings) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-center">
          <div className="w-24 h-24 rounded-full border-8 border-slate-700 border-t-blue-400 animate-spin mx-auto mb-8" />
          <p className="text-5xl text-slate-300">Loading display...</p>
        </div>
      </div>
    );
  }

  const bgColor = displaySettings.theme === "dark" ? "bg-slate-900" : "bg-white";
  const textColor = displaySettings.theme === "dark" ? "text-white" : "text-slate-900";
  const secondaryTextColor = displaySettings.theme === "dark" ? "text-slate-400" : "text-slate-600";

  return (
    <div className={`min-h-screen ${bgColor} flex flex-col`}>
      {/* Header with Area Name */}
      <div className={`border-b-4 ${displaySettings.theme === "dark" ? "border-slate-700" : "border-slate-300"} py-8 px-12`}>
        <h1 className={`text-9xl font-bold ${textColor} text-center`}>
          {area.displayName}
        </h1>
      </div>

      {/* Main Content Area - Jobs Display */}
      <div className="flex-1 flex items-center justify-center p-12">
        {jobMappings && jobMappings.length > 0 ? (
          <div className="w-full grid grid-cols-1 lg:grid-cols-2 gap-12 max-w-7xl">
            {jobMappings.map((mapping) => (
              <JobCard
                key={mapping.id}
                jobNumber={mapping.currentRmsJobNumber}
                jobId={mapping.currentRmsJobId}
                displaySettings={displaySettings}
                textColor={textColor}
                secondaryTextColor={secondaryTextColor}
                bgColor={bgColor}
              />
            ))}
          </div>
        ) : (
          <div className="text-center">
            <AlertCircle className={`w-40 h-40 mx-auto mb-8 ${secondaryTextColor}`} />
            <p className={`text-6xl font-semibold ${secondaryTextColor}`}>
              No jobs assigned to this area
            </p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className={`border-t-4 ${displaySettings.theme === "dark" ? "border-slate-700" : "border-slate-300"} py-6 px-12 flex items-center justify-between`}>
        <div className={`flex items-center gap-4 ${secondaryTextColor}`}>
          <RefreshCw className="w-8 h-8" />
          <span className="text-2xl">Refresh: {displaySettings.refreshIntervalSeconds}s</span>
        </div>
        <div className={`flex items-center gap-4 ${secondaryTextColor}`}>
          <Clock className="w-8 h-8" />
          <span className="text-2xl">{format(new Date(), "HH:mm:ss")}</span>
        </div>
      </div>
    </div>
  );
}

interface JobCardProps {
  jobNumber: string;
  jobId: string;
  displaySettings: any;
  textColor: string;
  secondaryTextColor: string;
  bgColor: string;
}

function JobCard({
  jobNumber,
  jobId,
  displaySettings,
  textColor,
  secondaryTextColor,
  bgColor,
}: JobCardProps) {
  const { data: jobDetails, isLoading } = trpc.warehouse.getJobDetails.useQuery(
    { jobId },
    { refetchInterval: displaySettings.refreshIntervalSeconds * 1000 }
  );

  if (isLoading) {
    return (
      <div className={`${bgColor} border-4 border-blue-500 rounded-2xl p-12 flex items-center justify-center min-h-96`}>
        <div className="w-16 h-16 rounded-full border-8 border-slate-700 border-t-blue-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className={`${bgColor} border-4 border-blue-500 rounded-2xl p-12 hover:border-blue-400 transition-colors min-h-96 flex flex-col justify-between`}>
      {/* Job Number */}
      <div className="mb-8">
        <p className={`${secondaryTextColor} text-3xl font-semibold mb-4 uppercase tracking-wider`}>
          Job Number
        </p>
        <p className={`text-8xl font-bold ${textColor}`}>
          {jobNumber}
        </p>
      </div>

      {/* Job Title */}
      {displaySettings.showJobTitle && jobDetails?.jobTitle && (
        <div className="mb-8">
          <p className={`${secondaryTextColor} text-3xl font-semibold mb-4 uppercase tracking-wider`}>
            Job Title
          </p>
          <p className={`text-5xl font-bold ${textColor} line-clamp-2`}>
            {jobDetails.jobTitle}
          </p>
        </div>
      )}

      {/* Client Name */}
      {jobDetails?.clientName && (
        <div className="mb-8">
          <p className={`${secondaryTextColor} text-3xl font-semibold mb-4 uppercase tracking-wider`}>
            Client
          </p>
          <p className={`text-5xl font-bold ${textColor} line-clamp-2`}>
            {jobDetails.clientName}
          </p>
        </div>
      )}

      {/* Load Date & Time */}
      {displaySettings.showLoadTime && jobDetails?.loadDate && (
        <div className="pt-8 border-t-2 border-slate-600">
          <p className={`${secondaryTextColor} text-3xl font-semibold mb-4 uppercase tracking-wider`}>
            Load Date & Time
          </p>
          <div className="flex items-baseline gap-6">
            <p className={`text-7xl font-bold ${textColor}`}>
              {format(new Date(jobDetails.loadDate), "MMM dd")}
            </p>
            {jobDetails.loadTime && (
              <p className={`text-6xl font-bold ${textColor}`}>
                {jobDetails.loadTime}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
