export type SelectableTopicQueueItem = {
  topic: {
    slug: string;
    status: string;
  };
};

export type TopicSelectionSummary = {
  selectedCount: number;
  projectCreatableCount: number;
  droppableCount: number;
};

function buildSelectedTopicSlugSet(selectedTopicSlugs: string[]): Set<string> {
  return new Set(selectedTopicSlugs);
}

export function toggleTopicSelection(selectedTopicSlugs: string[], topicSlug: string): string[] {
  if (selectedTopicSlugs.includes(topicSlug)) {
    return selectedTopicSlugs.filter((slug) => slug !== topicSlug);
  }

  return [...selectedTopicSlugs, topicSlug];
}

export function collectBatchProjectCreatableTopicSlugs(
  topicQueueItems: SelectableTopicQueueItem[],
  selectedTopicSlugs: string[],
): string[] {
  const selectedSet = buildSelectedTopicSlugSet(selectedTopicSlugs);
  return topicQueueItems
    .filter((item) => selectedSet.has(item.topic.slug) && item.topic.status === "pending")
    .map((item) => item.topic.slug);
}

export function collectBatchDroppableTopicSlugs(
  topicQueueItems: SelectableTopicQueueItem[],
  selectedTopicSlugs: string[],
): string[] {
  const selectedSet = buildSelectedTopicSlugSet(selectedTopicSlugs);
  return topicQueueItems
    .filter(
      (item) =>
        selectedSet.has(item.topic.slug) && (item.topic.status === "pending" || item.topic.status === "drafting"),
    )
    .map((item) => item.topic.slug);
}

export function buildTopicSelectionSummary({
  selectedTopicSlugs,
  topicQueueItems,
}: {
  selectedTopicSlugs: string[];
  topicQueueItems: SelectableTopicQueueItem[];
}): TopicSelectionSummary {
  return {
    selectedCount: selectedTopicSlugs.length,
    projectCreatableCount: collectBatchProjectCreatableTopicSlugs(topicQueueItems, selectedTopicSlugs).length,
    droppableCount: collectBatchDroppableTopicSlugs(topicQueueItems, selectedTopicSlugs).length,
  };
}
