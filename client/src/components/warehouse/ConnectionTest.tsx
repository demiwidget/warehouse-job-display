import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { toast } from "sonner";

export function ConnectionTest() {
  const [tested, setTested] = useState(false);
  const [result, setResult] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const { refetch } = trpc.warehouse.testConnection.useQuery(undefined, {
    enabled: false,
  });

  const handleTest = async () => {
    setIsLoading(true);
    try {
      const queryResult = await refetch();
      if (queryResult.data) {
        const isSuccess = queryResult.data.success === true;
        setResult(isSuccess);
        setTested(true);
        if (isSuccess) {
          toast.success("Current-RMS connection successful!");
        } else {
          toast.error(
            queryResult.data.error || "Current-RMS connection failed. Check your credentials."
          );
        }
      }
    } catch (error: any) {
      setResult(false);
      setTested(true);
      toast.error(error.message || "Connection test failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Card
      className={`p-4 border-2 ${
        result === true
          ? "border-green-500 bg-green-500/10"
          : result === false
            ? "border-red-500 bg-red-500/10"
            : "border-slate-700 bg-slate-800"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {result === true && <CheckCircle2 className="w-6 h-6 text-green-400" />}
          {result === false && <AlertCircle className="w-6 h-6 text-red-400" />}
          {!tested && (
            <div className="w-6 h-6 rounded-full border-2 border-slate-600 border-t-blue-400 animate-spin" />
          )}

          <div>
            <h3 className="font-semibold text-white">
              {result === true && "Current-RMS Connected"}
              {result === false && "Connection Failed"}
              {!tested && "Test Connection"}
            </h3>
            <p className="text-sm text-slate-400">
              {result === true && "Your Current-RMS API credentials are valid"}
              {result === false &&
                "Unable to connect to Current-RMS. Verify your API key and subdomain."}
              {!tested && "Click the button to test your Current-RMS API connection"}
            </p>
          </div>
        </div>

        <Button
          onClick={handleTest}
          disabled={isLoading}
          variant={result === true ? "outline" : "default"}
          className={
            result === true ? "border-green-500 text-green-400 hover:bg-green-500/10" : ""
          }
        >
          {isLoading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
          {isLoading ? "Testing..." : "Test Connection"}
        </Button>
      </div>
    </Card>
  );
}
