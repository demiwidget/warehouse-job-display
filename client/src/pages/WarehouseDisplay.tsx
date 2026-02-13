import { useEffect, useState } from "react";
import { useParams } from "wouter";
import { trpc } from "@/lib/trpc";
import { AlertCircle, Clock, Keyboard, Maximize2, Minimize2, Moon, RefreshCw, Sun } from "lucide-react";
import { format } from "date-fns";

export default function WarehouseDisplay() {
  const { areaId } = useParams<{ areaId: string }>();
  const [clockTick, setClockTick] = useState(0);
  const [showKeyboardHelp, setShowKeyboardHelp] = useState(false);
  const [themeOverride, setThemeOverride] = useState<"dark" | "light" | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(Boolean(document.fullscreenElement));
  const utils = trpc.useUtils();

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

  useEffect(() => {
    const interval = setInterval(() => setClockTick((c) => c + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const onFullScreenChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFullScreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullScreenChange);
  }, []);

  useEffect(() => {
    const toggleFullscreen = async () => {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen();
      }
    };

    const onKeyDown = async (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === "f") {
        event.preventDefault();
        try {
          await toggleFullscreen();
        } catch {
          // noop
        }
      }

      if (key === "r") {
        event.preventDefault();
        await Promise.all([
          utils.warehouse.getArea.invalidate(),
          utils.warehouse.getDisplaySettings.invalidate(),
          utils.warehouse.getAreaJobs.invalidate(),
          utils.warehouse.getJobDetails.invalidate(),
        ]);
      }

      if (key === "t") {
        event.preventDefault();
        setThemeOverride((current) => {
          const baseTheme = displaySettings?.theme === "dark" ? "dark" : "light";
          const currentTheme = current ?? baseTheme;
          return currentTheme === "dark" ? "light" : "dark";
        });
      }

      if (key === "?" || (event.shiftKey && key === "/") || key === "h") {
        event.preventDefault();
        setShowKeyboardHelp((v) => !v);
      }

      if (key === "escape") {
        setShowKeyboardHelp(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [displaySettings?.theme, utils.warehouse]);

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

  const activeTheme = themeOverride ?? displaySettings.theme;
  const bgColor = activeTheme === "dark" ? "bg-slate-900" : "bg-white";
  const textColor = activeTheme === "dark" ? "text-white" : "text-slate-900";
  const secondaryTextColor = activeTheme === "dark" ? "text-slate-400" : "text-slate-600";

  return (
    <div className={`min-h-screen ${bgColor} flex flex-col`}>
      <div className={`border-b-4 ${activeTheme === "dark" ? "border-slate-700" : "border-slate-300"} py-8 px-12`}>
        <h1 className={`text-9xl font-bold ${textColor} text-center`}>
          {area.displayName}
        </h1>
      </div>

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

      <div className={`border-t-4 ${activeTheme === "dark" ? "border-slate-700" : "border-slate-300"} py-6 px-12 flex items-center justify-between`}>
        <div className={`flex items-center gap-4 ${secondaryTextColor}`}>
          <RefreshCw className="w-8 h-8" />
          <span className="text-2xl">Refresh: {displaySettings.refreshIntervalSeconds}s</span>
        </div>
        <div className={`flex items-center gap-4 ${secondaryTextColor}`}>
          <Keyboard className="w-8 h-8" />
          <span className="text-2xl">H / ? for shortcuts</span>
        </div>
        <div className={`flex items-center gap-4 ${secondaryTextColor}`}>
          <Clock className="w-8 h-8" />
          <span className="text-2xl">{format(new Date(), "HH:mm:ss")}</span>
        </div>
      </div>

      {showKeyboardHelp && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-6">
          <div className={`w-full max-w-2xl rounded-2xl border ${activeTheme === "dark" ? "bg-slate-900 border-slate-700 text-white" : "bg-white border-slate-300 text-slate-900"} p-8`}>
            <h2 className="text-4xl font-bold mb-6">Display Shortcuts</h2>
            <div className="space-y-4 text-2xl">
              <ShortcutRow icon={isFullscreen ? <Minimize2 className="w-7 h-7" /> : <Maximize2 className="w-7 h-7" />} label="F" description="Toggle fullscreen" />
              <ShortcutRow icon={<RefreshCw className="w-7 h-7" />} label="R" description="Refresh display data" />
              <ShortcutRow icon={activeTheme === "dark" ? <Sun className="w-7 h-7" /> : <Moon className="w-7 h-7" />} label="T" description="Toggle light/dark theme" />
              <ShortcutRow icon={<Keyboard className="w-7 h-7" />} label="H / ?" description="Show/hide shortcuts" />
              <ShortcutRow icon={<AlertCircle className="w-7 h-7" />} label="Esc" description="Close shortcut panel" />
            </div>
          </div>
        </div>
      )}

      <span className="sr-only">{clockTick}</span>
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

interface ShortcutRowProps {
  icon: React.ReactNode;
  label: string;
  description: string;
}

function ShortcutRow({ icon, label, description }: ShortcutRowProps) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-700/40 px-5 py-4">
      <div className="flex items-center gap-3 font-semibold">
        {icon}
        <span>{description}</span>
      </div>
      <kbd className="rounded bg-slate-700/50 px-3 py-1 text-xl font-bold text-white">{label}</kbd>
    </div>
  );
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
      <div className="mb-8">
        <p className={`${secondaryTextColor} text-3xl font-semibold mb-4 uppercase tracking-wider`}>
          Job Number
        </p>
        <p className={`text-8xl font-bold ${textColor}`}>
          {jobNumber}
        </p>
      </div>

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
