# Plant ailment guides

My Garden Markdown remains authoritative. Its additive `tables.ailments` export contains stable IDs, categories (pest, disease, environment, nutrient, symptom), checks/actions, sources, possible-cause links and image credits. Existing pest/disease IDs and plant associations remain unchanged.

PMS migration 008 adds the `ailments` table. Explicit My Garden imports add missing guides and preserve existing values. `/ailments` lists all categories; `/ailments/<id>` displays a guide with the shared chatbot. The read-only API exposes new non-pest/disease categories as `ailment`; legacy entries keep their existing API kinds, avoiding duplicate RAG entries. The MCP reference schema accepts the new kind. Refresh the Almanac RAG source after import.

Photo endpoints serve copied reference images from the instance directory when present, otherwise redirect to the public garden archive. Photos include source credits and host-specific captions; the two user-supplied watering examples have no supplied source or licence. Missing photos remain empty rather than imply a diagnosis.

The 0melette site reads `tables.ailments` instead of a hard-coded list. Publishing requires the complete My Garden export/photos on its main branch and the updated site page. Local previews can read the local export before publishing.

Local verification: 30 imported guides; image endpoint returns JPEG; symptom links resolve; existing values survive repeat import; Chroma retrieval returns overwatering and underwatering references for a wilting question. Database backup was taken before the import.
