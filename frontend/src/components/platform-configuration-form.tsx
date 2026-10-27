"use client";

export interface PlatformValues {
  public_url: string;
  ollama_url: string;
  ollama_model: string;
  llm_analysis_enabled: boolean;
  correlation_enabled: boolean;
  knowledge_base_processing_enabled: boolean;
  knowledge_base_retrieval_enabled: boolean;
}

export const initialPlatformValues: PlatformValues = {
  public_url: "http://localhost:8080", ollama_url: "http://ollama:11434",
  ollama_model: "phi3:latest", llm_analysis_enabled: false, correlation_enabled: false,
  knowledge_base_processing_enabled: false, knowledge_base_retrieval_enabled: false,
};

export function PlatformConfigurationForm({ values, locked, onChange, disabled = false }: {
  values: PlatformValues; locked: string[]; onChange: (values: PlatformValues) => void; disabled?: boolean;
}) {
  const labels: Record<keyof PlatformValues, string> = {
    public_url: "Public TierX URL", ollama_url: "Ollama URL", ollama_model: "Ollama model",
    llm_analysis_enabled: "Enable analysis", correlation_enabled: "Enable correlation",
    knowledge_base_processing_enabled: "Process Knowledge Base files",
    knowledge_base_retrieval_enabled: "Retrieve Knowledge Base evidence",
  };
  return <div className="space-y-4">{(Object.keys(labels) as (keyof PlatformValues)[]).map((key) => (
    <label key={key} className="block text-sm">
      <span>{labels[key]}{locked.includes(key) ? " (managed by environment)" : ""}</span>
      {typeof values[key] === "boolean" ? (
        <input className="ml-3" type="checkbox" checked={values[key] as boolean}
          disabled={disabled || locked.includes(key)} onChange={(event) => {
            const next = { ...values, [key]: event.target.checked };
            if (key === "llm_analysis_enabled" && event.target.checked) next.correlation_enabled = true;
            onChange(next);
          }} />
      ) : <input className="mt-1 block w-full rounded border border-input bg-card p-2 disabled:opacity-60"
        value={values[key] as string} disabled={disabled || locked.includes(key)}
        onChange={(event) => onChange({ ...values, [key]: event.target.value })} />}
    </label>
  ))}</div>;
}
