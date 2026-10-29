import type { MountOptions } from './types';
import { WorkflowApp } from './workflow/WorkflowApp';

export function App({ options }: { options: MountOptions }) {
  if (!options.bootstrap || !options.bootstrap.workflow_available)
    return <p role="alert">制造工作区当前不可用，请稍后重试或联系管理员。</p>;
  return <WorkflowApp
    key={[options.bootstrap.user.id,options.bootstrap.dataset?.id,options.apiBase].join(':')}
    options={options}
  />;
}
