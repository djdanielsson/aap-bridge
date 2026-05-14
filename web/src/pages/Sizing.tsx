import { useState } from 'react';
import {
  Title,
  TextContent,
  Text,
  Form,
  FormGroup,
  FormSection,
  TextInput,
  FormSelect,
  FormSelectOption,
  Button,
  Card,
  CardBody,
  CardTitle,
  Gallery,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Alert,
  ExpandableSection,
} from '@patternfly/react-core';
import { api } from '../api/client';

interface SizingResult {
  input: Record<string, unknown>;
  execution_nodes: Record<string, unknown>;
  controller: Record<string, unknown>;
  database: Record<string, unknown>;
  automation_hub: Record<string, unknown> | null;
  gateway: Record<string, unknown> | null;
  eda: Record<string, unknown> | null;
  redis: Record<string, unknown> | null;
  warnings: string[];
  validation_warnings: string[];
}

export function Sizing() {
  // Core inputs
  const [managedHosts, setManagedHosts] = useState('5000');
  const [playbooksPerDay, setPlaybooksPerDay] = useState('100');
  const [jobDuration, setJobDuration] = useState('0.5');
  const [tasksPerJob, setTasksPerJob] = useState('50');
  const [forks, setForks] = useState('10');
  const [verbosity, setVerbosity] = useState('1');
  const [hoursPerDay, setHoursPerDay] = useState('8');
  const [peakPattern, setPeakPattern] = useState('business_hours');
  // Advanced inputs
  const [numControllers, setNumControllers] = useState('2');
  const [concurrentJobs, setConcurrentJobs] = useState('0');
  const [pendingJobs, setPendingJobs] = useState('0');
  const [jobRetention, setJobRetention] = useState('720');
  const [factRetention, setFactRetention] = useState('720');
  const [hubNodes, setHubNodes] = useState('1');
  const [edaNodes, setEdaNodes] = useState('0');

  const [result, setResult] = useState<SizingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleCalculate = async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await api.calculateSizing({
        managed_hosts: parseInt(managedHosts),
        playbooks_per_day_peak: parseInt(playbooksPerDay),
        job_duration_hours: parseFloat(jobDuration),
        tasks_per_job: parseInt(tasksPerJob),
        forks_observed: parseInt(forks),
        verbosity_level: parseInt(verbosity),
        allowed_hours_per_day: parseFloat(hoursPerDay),
        peak_pattern: peakPattern,
        num_controllers: parseInt(numControllers),
        concurrent_jobs: parseInt(concurrentJobs),
        pending_jobs: parseInt(pendingJobs),
        job_retention_hours: parseInt(jobRetention),
        fact_retention_hours: parseInt(factRetention),
        hub_nodes: parseInt(hubNodes),
        eda_nodes: parseInt(edaNodes),
      });
      setResult(res as SizingResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Calculation failed');
    } finally {
      setLoading(false);
    }
  };

  const fmtVal = (val: unknown) => {
    if (val === null || val === undefined) return 'N/A';
    if (typeof val === 'number') return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2);
    return String(val);
  };

  const fmtKey = (key: string) => key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  const renderResultCard = (title: string, data: Record<string, unknown> | null, color?: string) => {
    if (!data) return null;
    return (
      <Card style={{ borderTop: color ? `3px solid ${color}` : undefined }}>
        <CardTitle>{title}</CardTitle>
        <CardBody>
          <DescriptionList isHorizontal isCompact>
            {Object.entries(data).map(([key, val]) => (
              <DescriptionListGroup key={key}>
                <DescriptionListTerm>{fmtKey(key)}</DescriptionListTerm>
                <DescriptionListDescription>{fmtVal(val)}</DescriptionListDescription>
              </DescriptionListGroup>
            ))}
          </DescriptionList>
        </CardBody>
      </Card>
    );
  };

  return (
    <>
      <Title headingLevel="h1" size="2xl">Sizing Calculator</Title>
      <TextContent style={{ marginBottom: 16 }}>
        <Text>Calculate AAP 2.6 infrastructure sizing based on Red Hat official formulas.</Text>
      </TextContent>

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <Card style={{ flex: '0 0 420px' }}>
          <CardTitle>Input Parameters</CardTitle>
          <CardBody>
            <Form>
              <FormSection title="Workload">
                <FormGroup label="Managed Hosts" isRequired fieldId="hosts">
                  <TextInput id="hosts" type="number" value={managedHosts} onChange={(_e, v) => setManagedHosts(v)} />
                </FormGroup>
                <FormGroup label="Playbooks / Day (Peak)" isRequired fieldId="ppd">
                  <TextInput id="ppd" type="number" value={playbooksPerDay} onChange={(_e, v) => setPlaybooksPerDay(v)} />
                </FormGroup>
                <FormGroup label="Avg Job Duration (hours)" fieldId="duration">
                  <TextInput id="duration" type="number" value={jobDuration} onChange={(_e, v) => setJobDuration(v)} />
                </FormGroup>
                <FormGroup label="Tasks / Job" fieldId="tasks">
                  <TextInput id="tasks" type="number" value={tasksPerJob} onChange={(_e, v) => setTasksPerJob(v)} />
                </FormGroup>
                <FormGroup label="Forks" fieldId="forks">
                  <TextInput id="forks" type="number" value={forks} onChange={(_e, v) => setForks(v)} />
                </FormGroup>
                <FormGroup label="Verbosity Level" fieldId="verbosity">
                  <FormSelect id="verbosity" value={verbosity} onChange={(_e, v) => setVerbosity(v)}>
                    <FormSelectOption value="0" label="0 - Minimal" />
                    <FormSelectOption value="1" label="1 - Normal" />
                    <FormSelectOption value="2" label="2 - Verbose" />
                    <FormSelectOption value="3" label="3 - More Verbose" />
                    <FormSelectOption value="4" label="4 - Debug" />
                  </FormSelect>
                </FormGroup>
                <FormGroup label="Automation Hours / Day" fieldId="hours">
                  <TextInput id="hours" type="number" value={hoursPerDay} onChange={(_e, v) => setHoursPerDay(v)} />
                </FormGroup>
                <FormGroup label="Peak Pattern" fieldId="pattern">
                  <FormSelect id="pattern" value={peakPattern} onChange={(_e, v) => setPeakPattern(v)}>
                    <FormSelectOption value="distributed_24x7" label="Distributed 24x7" />
                    <FormSelectOption value="business_hours" label="Business Hours" />
                    <FormSelectOption value="batch_window" label="Batch Window" />
                    <FormSelectOption value="mixed" label="Mixed" />
                  </FormSelect>
                </FormGroup>
              </FormSection>

              <ExpandableSection toggleText="Advanced Settings">
                <FormGroup label="Controller Nodes" fieldId="controllers">
                  <TextInput id="controllers" type="number" value={numControllers} onChange={(_e, v) => setNumControllers(v)} />
                </FormGroup>
                <FormGroup label="Max Concurrent Jobs (0=auto)" fieldId="concurrent">
                  <TextInput id="concurrent" type="number" value={concurrentJobs} onChange={(_e, v) => setConcurrentJobs(v)} />
                </FormGroup>
                <FormGroup label="Typical Pending Jobs" fieldId="pending">
                  <TextInput id="pending" type="number" value={pendingJobs} onChange={(_e, v) => setPendingJobs(v)} />
                </FormGroup>
                <FormGroup label="Job Retention (hours)" fieldId="jobret">
                  <TextInput id="jobret" type="number" value={jobRetention} onChange={(_e, v) => setJobRetention(v)} />
                </FormGroup>
                <FormGroup label="Fact Retention (hours)" fieldId="factret">
                  <TextInput id="factret" type="number" value={factRetention} onChange={(_e, v) => setFactRetention(v)} />
                </FormGroup>
                <FormGroup label="Automation Hub Nodes (0=disabled)" fieldId="hub">
                  <TextInput id="hub" type="number" value={hubNodes} onChange={(_e, v) => setHubNodes(v)} />
                </FormGroup>
                <FormGroup label="EDA Nodes (0=disabled)" fieldId="eda">
                  <TextInput id="eda" type="number" value={edaNodes} onChange={(_e, v) => setEdaNodes(v)} />
                </FormGroup>
              </ExpandableSection>

              <Button variant="primary" onClick={handleCalculate} isLoading={loading} isDisabled={loading} style={{ marginTop: 16 }}>
                Calculate
              </Button>
            </Form>
          </CardBody>
        </Card>

        <div style={{ flex: 1, minWidth: 300 }}>
          {error && <Alert variant="danger" isInline title={error} style={{ marginBottom: 16 }} />}

          {result && result.warnings.length > 0 && (
            <Alert variant="warning" isInline title="Input Warnings" style={{ marginBottom: 16 }}>
              <ul>{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </Alert>
          )}

          {result && result.validation_warnings.length > 0 && (
            <Alert variant="info" isInline title="Validation Notes" style={{ marginBottom: 16 }}>
              <ul>{result.validation_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </Alert>
          )}

          {result && (
            <Gallery hasGutter minWidths={{ default: '300px' }}>
              {renderResultCard('Execution Nodes', result.execution_nodes, '#0066cc')}
              {renderResultCard('Controller', result.controller, '#3e8635')}
              {renderResultCard('Database', result.database, '#f0ab00')}
              {renderResultCard('Automation Hub', result.automation_hub, '#6753ac')}
              {renderResultCard('Platform Gateway', result.gateway, '#009596')}
              {renderResultCard('Event-Driven Ansible', result.eda, '#c9190b')}
              {renderResultCard('Redis', result.redis, '#ec7a08')}
            </Gallery>
          )}
        </div>
      </div>
    </>
  );
}
