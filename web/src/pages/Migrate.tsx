import { useState, useEffect, useCallback } from 'react';
import {
  Button,
  Title,
  TextContent,
  Text,
  Alert,
  Flex,
  FlexItem,
  Card,
  CardBody,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Divider,
  Checkbox,
} from '@patternfly/react-core';
import { api } from '../api/client';
import { LogViewer } from '../components/LogViewer';
import { MigrationPreview } from '../components/MigrationPreview';
import type { Connection } from '../types/connection';
import type { MigrationPreviewData } from '../types/resources';

const TUI_ACTIONS = [
  { id: 'cleanup', label: '0. Cleanup' },
  { id: 'prep', label: '1. Prep Phase (Discover & Schema)' },
  { id: 'export', label: '2. Export (All)' },
  { id: 'transform', label: '3. Transform (All)' },
  { id: 'import1', label: '4. Import Phase 1 (Base Resources)' },
  { id: 'import2', label: '5. Import Phase 2 (Patch Projects + Automation)' },
] as const;

type ActionId = typeof TUI_ACTIONS[number]['id'];

export function Migrate() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [destId, setDestId] = useState('');
  const [activeJobId, setActiveJobId] = useState('');
  const [runningAction, setRunningAction] = useState<ActionId | 'preview' | null>(null);
  const [error, setError] = useState('');
  const [statusMsg, setStatusMsg] = useState('');
  const [previewData, setPreviewData] = useState<MigrationPreviewData | null>(null);
  const [previewJobId, setPreviewJobId] = useState('');
  const [prepForce, setPrepForce] = useState(false);

  const loadConnections = useCallback(async () => {
    const conns = await api.listConnections() as Connection[];
    setConnections(conns);
  }, []);

  useEffect(() => { loadConnections(); }, [loadConnections]);

  const pairSelected = Boolean(sourceId && destId && sourceId !== destId);

  const runAction = async (action: ActionId) => {
    if (!pairSelected || runningAction) return;
    setError('');
    setStatusMsg('');
    setPreviewData(null);
    setRunningAction(action);

    try {
      let result: { job_id: string };
      switch (action) {
        case 'cleanup':
          result = await api.migrationCleanup(sourceId, destId);
          break;
        case 'prep':
          result = await api.migrationPrep(sourceId, destId, prepForce);
          break;
        case 'export':
          result = await api.migrationExport(sourceId, destId);
          break;
        case 'transform':
          result = await api.migrationTransform(sourceId, destId);
          break;
        case 'import1':
          result = await api.migrationImport(sourceId, destId, 'phase1');
          break;
        case 'import2':
          result = await api.migrationImport(sourceId, destId, 'phase2');
          break;
      }
      setActiveJobId(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setRunningAction(null);
    }
  };

  const runPreview = async () => {
    if (!pairSelected || runningAction) return;
    setError('');
    setStatusMsg('');
    setPreviewData(null);
    setRunningAction('preview');

    try {
      const result = await api.migrationPreview(sourceId, destId);
      setActiveJobId(result.job_id);
      setPreviewJobId(result.job_id);
      pollPreview(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setRunningAction(null);
    }
  };

  const pollPreview = async (jobId: string) => {
    const poll = async (attempt = 0) => {
      try {
        const resp = await api.getMigrationPreview(jobId) as MigrationPreviewData;
        setPreviewData(resp);
        setRunningAction(null);
        setStatusMsg('Preview complete.');
      } catch {
        try {
          const job = await api.getJob(jobId) as { status: string; error?: string };
          if (job.status === 'failed') {
            setError(job.error || 'Preview failed');
            setRunningAction(null);
            return;
          }
          if (job.status === 'completed') {
            setRunningAction(null);
            return;
          }
          if (attempt < 600) {
            setTimeout(() => { void poll(attempt + 1); }, 1500);
          } else {
            setError('Preview timed out');
            setRunningAction(null);
          }
        } catch (jobErr) {
          if (attempt < 600) {
            setTimeout(() => { void poll(attempt + 1); }, 1500);
          } else {
            setError(jobErr instanceof Error ? jobErr.message : 'Preview failed');
            setRunningAction(null);
          }
        }
      }
    };
    setTimeout(() => { void poll(); }, 2000);
  };

  const handleJobClose = (status: string) => {
    setRunningAction(null);
    if (status === 'completed') {
      setStatusMsg('Job completed successfully.');
    } else if (status === 'failed') {
      setError('Job failed. See log for details.');
    } else if (status === 'cancelled') {
      setStatusMsg('Job cancelled.');
    }
  };

  const sources = connections.filter(c => c.role === 'source');
  const destinations = connections.filter(c => c.role === 'destination');

  return (
    <>
      <Title headingLevel="h1" size="2xl">Migrate</Title>
      <TextContent style={{ marginBottom: 16 }}>
        <Text>
          Same menu as the CLI/TUI: run each phase individually against the selected source and
          destination. Export and transform use parallel resource processing when enabled in
          <code> config/config.yaml</code>. Logs stream below in a TUI-like format.
        </Text>
      </TextContent>

      {connections.length < 2 && (
        <Alert variant="info" isInline title="You need at least 2 connections configured." />
      )}

      <Card style={{ marginBottom: 16 }}>
        <CardBody>
          <Flex direction={{ default: 'column' }} spaceItems={{ default: 'spaceItemsMd' }}>
            <FlexItem>
              <FormGroup label="Source" fieldId="source-select">
                <FormSelect
                  id="source-select"
                  value={sourceId}
                  onChange={(_e, val) => setSourceId(val)}
                  aria-label="Select source connection"
                >
                  <FormSelectOption key="" value="" label="-- Select source --" isDisabled />
                  {sources.map(c => (
                    <FormSelectOption
                      key={c.id}
                      value={c.id}
                      label={`${c.name} (v${c.version || '?'}) — ${c.url}`}
                      isDisabled={c.id === destId}
                    />
                  ))}
                </FormSelect>
              </FormGroup>
            </FlexItem>
            <FlexItem>
              <FormGroup label="Destination" fieldId="dest-select">
                <FormSelect
                  id="dest-select"
                  value={destId}
                  onChange={(_e, val) => setDestId(val)}
                  aria-label="Select destination connection"
                >
                  <FormSelectOption key="" value="" label="-- Select destination --" isDisabled />
                  {destinations.map(c => (
                    <FormSelectOption
                      key={c.id}
                      value={c.id}
                      label={`${c.name} (v${c.version || '?'}) — ${c.url}`}
                      isDisabled={c.id === sourceId}
                    />
                  ))}
                </FormSelect>
              </FormGroup>
            </FlexItem>
            {sourceId && destId && sourceId === destId && (
              <FlexItem>
                <Alert variant="danger" isInline title="Source and destination cannot be the same connection." />
              </FlexItem>
            )}
          </Flex>
        </CardBody>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <CardBody>
          <Title headingLevel="h3" size="md" style={{ marginBottom: 12 }}>Main Menu</Title>
          <Flex direction={{ default: 'column' }} spaceItems={{ default: 'spaceItemsSm' }}>
            {TUI_ACTIONS.map(action => (
              <FlexItem key={action.id}>
                {action.id === 'prep' ? (
                  <Flex
                    direction={{ default: 'column' }}
                    spaceItems={{ default: 'spaceItemsSm' }}
                    style={{ maxWidth: 520 }}
                  >
                    <FlexItem>
                      <Button
                        variant="secondary"
                        onClick={() => { void runAction(action.id); }}
                        isDisabled={!pairSelected || runningAction !== null}
                        isLoading={runningAction === action.id}
                        style={{ justifyContent: 'flex-start', width: '100%' }}
                      >
                        {action.label}
                      </Button>
                    </FlexItem>
                    <FlexItem>
                      <Checkbox
                        id="prep-force"
                        label="Force schema re-collection (even if schemas already exist)"
                        isChecked={prepForce}
                        onChange={(_e, checked) => setPrepForce(checked)}
                        isDisabled={!pairSelected || runningAction !== null}
                      />
                    </FlexItem>
                  </Flex>
                ) : (
                  <Button
                    variant={action.id === 'cleanup' ? 'warning' : 'secondary'}
                    onClick={() => { void runAction(action.id); }}
                    isDisabled={!pairSelected || runningAction !== null}
                    isLoading={runningAction === action.id}
                    style={{ justifyContent: 'flex-start', width: '100%', maxWidth: 520 }}
                  >
                    {action.label}
                  </Button>
                )}
              </FlexItem>
            ))}
          </Flex>

          <Divider style={{ margin: '16px 0' }} />

          <Title headingLevel="h4" size="md" style={{ marginBottom: 8 }}>Web UI only</Title>
          <Button
            variant="primary"
            onClick={() => { void runPreview(); }}
            isDisabled={!pairSelected || runningAction !== null}
            isLoading={runningAction === 'preview'}
          >
            Preview Migration
          </Button>
        </CardBody>
      </Card>

      {error && <Alert variant="danger" isInline title={error} style={{ marginBottom: 16 }} />}
      {statusMsg && <Alert variant="success" isInline title={statusMsg} style={{ marginBottom: 16 }} />}

      {activeJobId && (
        <div style={{ marginBottom: 16 }}>
          <Title headingLevel="h3" style={{ marginBottom: 8 }}>Job Log</Title>
          <LogViewer jobId={activeJobId} onClose={handleJobClose} />
        </div>
      )}

      {previewData && previewJobId && (
        <div style={{ marginBottom: 16 }}>
          <Title headingLevel="h3" style={{ marginBottom: 8 }}>Preview Results</Title>
          <MigrationPreview preview={previewData} />
        </div>
      )}
    </>
  );
}
