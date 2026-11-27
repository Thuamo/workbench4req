import {Presentation, PresentationFile} from '@oai/artifact-tool';

const destination = process.argv[2];
if (!destination) throw new Error('Supply the output PPTX path.');

const presentation = Presentation.create({slideSize: {width: 1280, height: 720}});
const slide = presentation.slides.add();
slide.background.fill = '#F6F8FB';
const font = 'Microsoft YaHei';
const noLine = {fill: 'none', width: 0};

function rectangle(name, x, y, width, height, fill) {
  return slide.shapes.add({name, geometry: 'rect', position: {left:x, top:y, width, height}, fill, line:noLine});
}

function text(name, x, y, width, height, size, color, {bold = false, verticalAlignment = 'top'} = {}) {
  const shape = slide.shapes.add({name, geometry:'textbox', fill:'none', line:noLine,
    position:{left:x, top:y, width, height}});
  shape.text = `REPORT_${name.toUpperCase()}`;
  shape.text.style = {typeface:font, fontSize:`${size}px`, color, bold, verticalAlignment,
    insets:0, wrap:'square', autoFit:'none'};
}

rectangle('header', 0, 0, 1280, 202, '#14243D');
rectangle('accent', 64, 40, 60, 5, '#5DD9C1');
text('headline', 64, 57, 1152, 102, 42, '#FFFFFF', {bold:true, verticalAlignment:'middle'});
text('context', 66, 165, 1148, 27, 20, '#D1E1F4');

for (let i = 1; i <= 3; i++) {
  const top = 228 + (i - 1) * 151;
  rectangle(`divider_${i}`, 65, top, 1149, 1.5, '#D5DEE9');
  text(`label_${i}`, 65, top + 21, 228, 68, 29, '#1B5271', {bold:true});
  text(`detail_${i}`, 315, top + 23, 900, 106, 25, '#1D2F48');
}

slide.speakerNotes.text = 'REPORT_SPEAKER_NOTES';
const deck = await PresentationFile.exportPptx(presentation);
await deck.save(destination);
