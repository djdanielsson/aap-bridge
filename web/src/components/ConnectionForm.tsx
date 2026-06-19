import { useEffect, useState } from 'react';
import {
  Alert,
  Modal,
  ModalVariant,
  Form,
  FormGroup,
  FormHelperText,
  HelperText,
  HelperTextItem,
  TextInput,
  FormSelect,
  FormSelectOption,
  Checkbox,
  Button,
} from '@patternfly/react-core';
import { api } from '../api/client';
import type { Connection, ConnectionPayload, SupportedVersions } from '../types/connection';

const MASKED_TOKEN = '********';
const DEFAULT_SOURCE_VERSION = '2.4';
const DEFAULT_TARGET_VERSION = '2.6';

function defaultVersionForRole(role: 'source' | 'destination', versions: SupportedVersions | null): string {
  if (!versions) {
    return role === 'destination' ? DEFAULT_TARGET_VERSION : DEFAULT_SOURCE_VERSION;
  }
  const options = role === 'destination' ? versions.target_versions : versions.source_versions;
  if (role === 'destination') {
    return options.includes(DEFAULT_TARGET_VERSION) ? DEFAULT_TARGET_VERSION : options[options.length - 1];
  }
  return options.includes(DEFAULT_SOURCE_VERSION) ? DEFAULT_SOURCE_VERSION : options[options.length - 1];
}

interface Props {
  isOpen: boolean;
  initial?: Partial<Connection>;
  onSave: (conn: ConnectionPayload) => Promise<void>;
  onClose: () => void;
}

export function ConnectionForm({ isOpen, initial, onSave, onClose }: Props) {
  const [name, setName] = useState(initial?.name || '');
  const [role, setRole] = useState<'source' | 'destination'>(initial?.role || 'source');
  const [url, setUrl] = useState(initial?.url || '');
  const [token, setToken] = useState('');
  const [verifySsl, setVerifySsl] = useState(initial?.verify_ssl ?? true);
  const [versions, setVersions] = useState<SupportedVersions | null>(null);
  const [version, setVersion] = useState(initial?.version || DEFAULT_SOURCE_VERSION);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    void api.getSupportedVersions().then(setVersions).catch(() => setVersions(null));
  }, [isOpen]);

  useEffect(() => {
    if (!versions) return;
    const options = role === 'destination' ? versions.target_versions : versions.source_versions;
    if (!options.includes(version)) {
      setVersion(defaultVersionForRole(role, versions));
    }
  }, [versions, role, version]);

  const handleRoleChange = (newRole: 'source' | 'destination') => {
    setRole(newRole);
    if (!versions) return;
    const options = newRole === 'destination' ? versions.target_versions : versions.source_versions;
    if (!options.includes(version)) {
      setVersion(defaultVersionForRole(newRole, versions));
    }
  };

  const versionOptions = versions
    ? (role === 'destination' ? versions.target_versions : versions.source_versions)
    : [];

  const handleSubmit = async () => {
    const payload: ConnectionPayload = { name, role, url, version, verify_ssl: verifySsl };
    const trimmedToken = token.trim();
    if (!initial?.id || (trimmedToken && trimmedToken !== MASKED_TOKEN)) {
      payload.token = trimmedToken;
    }
    setSaving(true);
    setSaveError('');
    try {
      await onSave(payload);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      variant={ModalVariant.medium}
      title={initial?.name ? 'Edit Connection' : 'Add Connection'}
      actions={[
        <Button key="save" variant="primary" onClick={() => { void handleSubmit(); }} isLoading={saving} isDisabled={saving}>Save</Button>,
        <Button key="cancel" variant="link" onClick={onClose} isDisabled={saving}>Cancel</Button>,
      ]}
    >
      <Form isHorizontal>
        {saveError && (
          <Alert variant="danger" isInline title={saveError} style={{ marginBottom: 16 }} />
        )}
        <FormGroup label="Name" isRequired fieldId="name">
          <TextInput id="name" value={name} onChange={(_e, v) => setName(v)} placeholder="My AAP Instance" />
        </FormGroup>
        <FormGroup label="Role" fieldId="role">
          <FormSelect id="role" value={role} onChange={(_e, v) => handleRoleChange(v as 'source' | 'destination')}>
            <FormSelectOption value="source" label="Source (migrate FROM)" />
            <FormSelectOption value="destination" label="Destination (migrate TO)" />
          </FormSelect>
          <FormHelperText>
            <HelperText>
              <HelperTextItem>
                Source is the older AAP instance; destination is typically AAP 2.5+.
              </HelperTextItem>
            </HelperText>
          </FormHelperText>
        </FormGroup>
        <FormGroup label="AAP Version" isRequired fieldId="version">
          <FormSelect
            id="version"
            value={version}
            onChange={(_e, v) => setVersion(v)}
            isDisabled={versionOptions.length === 0}
          >
            {versionOptions.map((v) => (
              <FormSelectOption key={v} value={v} label={v} />
            ))}
          </FormSelect>
          <FormHelperText>
            <HelperText>
              <HelperTextItem>
                Select the AAP version for API routing. Older releases do not expose a reliable version from the API.
              </HelperTextItem>
            </HelperText>
          </FormHelperText>
        </FormGroup>
        <FormGroup label="URL" isRequired fieldId="url">
          <TextInput id="url" value={url} onChange={(_e, v) => setUrl(v)} placeholder="https://aap.example.com" />
          <FormHelperText>
            <HelperText>
              <HelperTextItem>
                Use the gateway root URL, such as <code>https://aap.example.com</code>.
              </HelperTextItem>
            </HelperText>
          </FormHelperText>
        </FormGroup>
        <FormGroup label="Token" fieldId="token">
          <TextInput id="token" type="password" value={token} onChange={(_e, v) => setToken(v)} placeholder="API authentication token" />
          <FormHelperText>
            <HelperText>
              <HelperTextItem>
                {initial?.id
                  ? 'Leave blank to keep the current token, or enter a new token to replace it.'
                  : 'Personal Access Token or OAuth2 token for API authentication'}
              </HelperTextItem>
            </HelperText>
          </FormHelperText>
        </FormGroup>
        <FormGroup fieldId="verify-ssl">
          <Checkbox
            id="verify-ssl"
            label="Verify SSL certificate"
            isChecked={verifySsl}
            onChange={(_e, v) => setVerifySsl(v)}
          />
        </FormGroup>
      </Form>
    </Modal>
  );
}
