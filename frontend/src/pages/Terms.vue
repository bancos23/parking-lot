<script setup>
import { computed } from 'vue'
import LegalPageShell from '@frontend/components/LegalPageShell.vue'
import { useT } from '@frontend/composables/i18n'

const { t } = useT()

const sectionBlueprints = [
  { key: 'scope', paragraphs: 2 },
  { key: 'accounts', paragraphs: 2, items: 3 },
  { key: 'acceptable_use', paragraphs: 1 },
  { key: 'operational_data', paragraphs: 2 },
  { key: 'changes', paragraphs: 1 },
]

const sections = computed(() => sectionBlueprints.map(({ key, paragraphs, items = 0 }) => ({
  title: t(`legal.terms.sections.${key}.title`),
  paragraphs: Array.from({ length: paragraphs }, (_, index) => t(`legal.terms.sections.${key}.paragraphs.${index}`)),
  items: Array.from({ length: items }, (_, index) => t(`legal.terms.sections.${key}.items.${index}`)),
})))
</script>

<template>
  <LegalPageShell
    :eyebrow="t('legal.terms.eyebrow')"
    :title="t('legal.terms.title')"
    :description="t('legal.terms.description')"
    :updated="t('legal.updated')"
    :sections="sections"
  />
</template>
