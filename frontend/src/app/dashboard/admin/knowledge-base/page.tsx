import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";


export default function PlatformKnowledgeBasePage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Select a tenant</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Knowledge Base files are tenant-scoped. Choose a specific tenant from
        the tenant switcher to view or upload its files.
      </CardContent>
    </Card>
  );
}
