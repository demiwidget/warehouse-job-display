import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { toast } from "sonner";

export function JobMappings() {
  const [selectedArea, setSelectedArea] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");

  const { data: areas } = trpc.warehouse.listAreas.useQuery();
  const { data: jobs, isLoading: jobsLoading } = trpc.warehouse.searchCurrentRmsJobs.useQuery(
    { query: searchQuery },
    { enabled: searchQuery.length > 0 }
  );
  const { data: areaJobs, refetch: refetchAreaJobs } = trpc.warehouse.getAreaJobs.useQuery(
    { areaId: parseInt(selectedArea) },
    { enabled: !!selectedArea }
  );

  const addJobMutation = trpc.warehouse.addJobToArea.useMutation({
    onSuccess: () => {
      toast.success("Job added to area");
      refetchAreaJobs();
      setSearchQuery("");
    },
    onError: (error) => {
      toast.error(error.message || "Failed to add job");
    },
  });

  const removeJobMutation = trpc.warehouse.removeJobFromArea.useMutation({
    onSuccess: () => {
      toast.success("Job removed from area");
      refetchAreaJobs();
    },
    onError: (error) => {
      toast.error(error.message || "Failed to remove job");
    },
  });

  const handleAddJob = (jobId: string, jobNumber: string) => {
    if (!selectedArea) {
      toast.error("Please select an area first");
      return;
    }
    addJobMutation.mutate({
      areaId: parseInt(selectedArea),
      currentRmsJobId: jobId,
      currentRmsJobNumber: jobNumber,
    });
  };

  return (
    <div className="space-y-6">
      {/* Area Selection */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">Select Area</label>
        <Select value={selectedArea} onValueChange={setSelectedArea}>
          <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
            <SelectValue placeholder="Choose an area..." />
          </SelectTrigger>
          <SelectContent className="bg-slate-800 border-slate-600">
            {areas?.map((area) => (
              <SelectItem key={area.id} value={String(area.id)} className="text-white">
                {area.displayName}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedArea && (
        <>
          {/* Search Jobs */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Search Current-RMS Jobs
            </label>
            <div className="flex gap-2">
              <Input
                placeholder="Search by job title or number..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-800 border-slate-600 text-white flex-1"
              />
              {jobsLoading && <Loader2 className="w-5 h-5 text-slate-400 animate-spin" />}
            </div>
          </div>

          {/* Available Jobs */}
          {searchQuery && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-slate-300">Available Jobs</h4>
              {jobsLoading ? (
                <div className="text-center py-4 text-slate-400">Searching...</div>
              ) : jobs && jobs.length > 0 ? (
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {jobs.map((job) => (
                    <Card
                      key={job.id}
                      className="p-3 border-slate-700 bg-slate-700/30 flex items-center justify-between"
                    >
                      <div className="flex-1">
                        <p className="font-medium text-white">{job.jobTitle}</p>
                        <p className="text-sm text-slate-400">Job #{job.jobNumber}</p>
                      </div>
                      <Button
                        size="sm"
                        onClick={() => handleAddJob(job.id, job.jobNumber)}
                        disabled={addJobMutation.isPending}
                        className="bg-green-600 hover:bg-green-700 gap-2"
                      >
                        <Plus className="w-4 h-4" />
                        Add
                      </Button>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="text-center py-4 text-slate-400">No jobs found</div>
              )}
            </div>
          )}

          {/* Current Area Jobs */}
          <div>
            <h4 className="text-sm font-medium text-slate-300 mb-2">Jobs in This Area</h4>
            {areaJobs && areaJobs.length > 0 ? (
              <div className="space-y-2">
                {areaJobs.map((mapping) => (
                  <Card
                    key={mapping.id}
                    className="p-3 border-slate-700 bg-slate-700/30 flex items-center justify-between"
                  >
                    <div>
                      <p className="font-medium text-white">Job #{mapping.currentRmsJobNumber}</p>
                      <p className="text-xs text-slate-400">ID: {mapping.currentRmsJobId}</p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => removeJobMutation.mutate({ mappingId: mapping.id })}
                      disabled={removeJobMutation.isPending}
                      className="text-red-400 hover:text-red-300 hover:bg-slate-600"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </Card>
                ))}
              </div>
            ) : (
              <div className="text-center py-4 text-slate-400">No jobs assigned yet</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
