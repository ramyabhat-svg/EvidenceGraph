import { describe, expect, it } from 'vitest';
import { anchorLabel, validateFiles } from './api';

describe('source anchor labels', () => {
  it('shows a CSV row without inventing a PDF page', () => {
    expect(anchorLabel({page: null, element_type: 'csv_row', table_id: null,
      row: 0, col: null, char_start: null, char_end: null})).toBe('csv row · row 0');
  });
  it('prints table positions and offsets including zero', () => {
    expect(anchorLabel({page: 3, element_type: 'table_cell', table_id: 'table-2',
      row: 0, col: 0, char_start: 0, char_end: 20})).toContain('row 0 · col 0 · characters 0–20');
  });
});
describe('upload validation', () => {
  it('requires the right extensions and nonempty input', () => {
    const pdf = new File(['pdf'], 'paper.PDF');
    expect(validateFiles(pdf)).toBeUndefined();
    expect(validateFiles(new File(['pdf'], 'paper.csv'))).toContain('PDF');
    expect(validateFiles(pdf, new File([], 'data.csv'))).toContain('1 byte');
  });
});
