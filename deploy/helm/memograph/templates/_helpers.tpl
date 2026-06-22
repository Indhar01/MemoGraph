{{/*
Standard chart helpers — name, fullname, labels, selectors, image ref.
Patterned after the Helm starter chart so consumers familiar with the
mainstream stack feel at home.
*/}}

{{- define "memograph.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "memograph.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "memograph.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "memograph.labels" -}}
helm.sh/chart: {{ include "memograph.chart" . }}
{{ include "memograph.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: memograph
{{- end -}}

{{- define "memograph.selectorLabels" -}}
app.kubernetes.io/name: {{ include "memograph.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "memograph.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "memograph.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Image reference — supports either tag or digest. Digest takes priority
because it pins immutably; tag is the default for less-formal deploys.
*/}}
{{- define "memograph.image" -}}
{{- $repo := .Values.image.repository -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" $repo .Values.image.digest -}}
{{- else -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{/*
Name of the Secret that holds api keys / OIDC secrets. If the user
supplied an existing Secret, use that; otherwise the chart-managed one.
*/}}
{{- define "memograph.apiKeySecretName" -}}
{{- if .Values.auth.apiKey.existingSecret -}}
{{- .Values.auth.apiKey.existingSecret -}}
{{- else -}}
{{- printf "%s-auth" (include "memograph.fullname" .) -}}
{{- end -}}
{{- end -}}
