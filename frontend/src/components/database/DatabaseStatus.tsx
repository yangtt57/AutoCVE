import { Server } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export function DatabaseStatus() {
  return <Badge variant="outline" className="gap-1.5"><Server className="h-3 w-3" />后端数据库</Badge>;
}

export function DatabaseStatusDetail() {
  return <div className="flex items-start gap-3 rounded-lg border p-4">
    <Server className="mt-0.5 h-5 w-5 text-muted-foreground" />
    <div className="space-y-1"><h4 className="text-sm font-semibold">后端数据库</h4>
      <p className="text-sm text-muted-foreground">数据通过后端 API 存储在 PostgreSQL 中，支持多用户、多设备访问。</p>
    </div>
  </div>;
}
