import JsonViewer from '../common/JsonViewer';
import type { DSL } from '../../types/api';

interface Props {
  dsl: DSL;
}

export default function DSLViewer({ dsl }: Props) {
  return <JsonViewer data={dsl} />;
}
