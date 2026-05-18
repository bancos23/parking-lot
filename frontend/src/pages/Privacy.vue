<script setup>
import { computed } from 'vue'
import LegalPageShell from '@frontend/components/LegalPageShell.vue'
import { useT } from '@frontend/composables/i18n'

const { t } = useT()

const sectionBlueprints = [
  { key: 'data', paragraphs: 1, items: 3 },
  { key: 'usage', paragraphs: 2 },
  { key: 'location', paragraphs: 2 },
  { key: 'retention', paragraphs: 2 },
  { key: 'choices', paragraphs: 1 },
]

const sections = computed(() => sectionBlueprints.map(({ key, paragraphs, items = 0 }) => ({
  title: t(`legal.privacy.sections.${key}.title`),
  paragraphs: Array.from({ length: paragraphs }, (_, index) => t(`legal.privacy.sections.${key}.paragraphs.${index}`)),
  items: Array.from({ length: items }, (_, index) => t(`legal.privacy.sections.${key}.items.${index}`)),
})))
</script>

<template>
  <LegalPageShell
    :eyebrow="t('legal.privacy.eyebrow')"
    :title="t('legal.privacy.title')"
    :description="t('legal.privacy.description')"
    :updated="t('legal.updated')"
    :sections="sections"
  />
</template>
