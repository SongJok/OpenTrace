import React from 'react';

type Citation = {
  source_type?: string;
  title?: string;
  snippet?: string;
  content_snippet?: string;
  evidence_level?: string;
};

type Props = {
  citations?: Citation[];
};

export default function DecisionTraceCard({ citations = [] }: Props) {
  const grouped = citations.reduce<Record<string, Citation[]>>((acc, item) => {
    const key = item.source_type || 'unknown';
    (acc[key] ||= []).push(item);
    return acc;
  }, {});

  return (
    <div>
      {Object.entries(grouped).map(([sourceType, items]) => (
        <section key={sourceType}>
          <h4>{sourceType === 'rag' ? '内部文档' : sourceType === 'web' ? '网络参考' : sourceType}</h4>
          {items.map((cite, idx) => (
            <div key={idx}>
              <strong>{cite.title || 'Citation'}</strong>
              <div>{cite.content_snippet || cite.snippet || ''}</div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
