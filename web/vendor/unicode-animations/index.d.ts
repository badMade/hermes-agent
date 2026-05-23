export type BrailleSpinnerName = "braille";

export interface UnicodeAnimation {
  interval: number;
  frames: string[];
}

declare const spinners: Record<BrailleSpinnerName, UnicodeAnimation>;
export { spinners };
export default spinners;
