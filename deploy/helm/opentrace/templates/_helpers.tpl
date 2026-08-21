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
{{- define "opentrace.image" -}}
{{- if .Values.image.digest -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" .Values.image.digest) -}}
{{- fail "image.digest 必须是 sha256: 后跟 64 位小写十六进制" -}}
{{- end -}}
{{ printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else -}}
{{- if eq .Values.config.appEnv "production" -}}
{{- fail "production 必须配置不可变的 image.digest=sha256:..." -}}
{{- end -}}
{{- $tag := required "image.tag 或 image.digest 必须配置" .Values.image.tag -}}
{{- if eq $tag "latest" -}}
{{- fail "禁止使用可漂移的 image.tag=latest；请使用版本 tag 或 digest" -}}
{{- end -}}
{{ printf "%s:%s" .Values.image.repository $tag }}
{{- end -}}
{{- end }}
{{- define "opentrace.commonEnv" -}}
- name: APP_ENV
  value: {{ .Values.config.appEnv | quote }}
- name: TRACE_ENABLED
  value: {{ .Values.config.traceEnabled | quote }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.config.otlpEndpoint | quote }}
- name: ENTERPRISE_TENANT_RLS_ENABLED
  value: {{ .Values.config.tenantRlsEnabled | quote }}
{{- end }}
{{- define "opentrace.env" -}}
{{- include "opentrace.commonEnv" . }}
- name: TOKEN_DB_URL
  valueFrom: {secretKeyRef: {name: {{ .Values.secret.existingSecret }}, key: {{ .Values.config.tokenDatabaseUrlSecretKey }}}}
- name: REDIS_URL
  valueFrom: {secretKeyRef: {name: {{ .Values.secret.existingSecret }}, key: {{ .Values.config.redisUrlSecretKey }}}}
{{- end }}
