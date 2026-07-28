{{- define "opentrace.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "opentrace.fullname" -}}
{{- if .Values.fullnameOverride }}{{ .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}{{ else }}{{ include "opentrace.name" . }}{{ end }}
{{- end }}
{{- define "opentrace.labels" -}}
app.kubernetes.io/name: {{ include "opentrace.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
{{- define "opentrace.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}{{ default (include "opentrace.fullname" .) .Values.serviceAccount.name }}{{ else }}{{ default "default" .Values.serviceAccount.name }}{{ end }}
{{- end }}
{{- define "opentrace.env" -}}
- name: APP_ENV
  value: {{ .Values.config.appEnv | quote }}
- name: TOKEN_DB_URL
  valueFrom: {secretKeyRef: {name: {{ .Values.secret.existingSecret }}, key: {{ .Values.config.tokenDatabaseUrlSecretKey }}}}
- name: REDIS_URL
  valueFrom: {secretKeyRef: {name: {{ .Values.secret.existingSecret }}, key: {{ .Values.config.redisUrlSecretKey }}}}
- name: TRACE_ENABLED
  value: {{ .Values.config.traceEnabled | quote }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.config.otlpEndpoint | quote }}
- name: ENTERPRISE_TENANT_RLS_ENABLED
  value: {{ .Values.config.tenantRlsEnabled | quote }}
{{- end }}
