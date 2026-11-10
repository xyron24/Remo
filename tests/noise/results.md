# Noise benchmark

Mean WER by condition (lower is better; fixtures: Timbre Hinglish, noise: synthetic overlays, 8k = telephony downsample):

| condition | mean WER |
|---|---|
| clean-16k | 7.9% |
| clean-8k | 7.9% |
| white-15db | 21.2% |
| white-5db | 21.2% |
| rumble-5db | 16.2% |
| babble-5db | 58.9% |
| white-5db-8k | 21.2% |

## Per clip

| clip | condition | WER | keywords | transcript |
|---|---|---|---|---|
| save-maths | clean-16k | 0.000 | 3/3 | याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है। |
| save-maths | clean-8k | 0.000 | 3/3 | याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है। |
| save-maths | white-15db | 0.000 | 3/3 | याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है। |
| save-maths | white-5db | 0.000 | 3/3 | याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है। |
| save-maths | rumble-5db | 0.000 | 3/3 | याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है। |
| save-maths | babble-5db | 0.600 | 2/3 | याद रात याद रात गणित में इंटीग्रेशन हो गया हो गया डिफरेंशियल |
| save-maths | white-5db-8k | 0.000 | 3/3 | याद रखना, गणित में इंटीग्रेशन हो गया, डिफरेंशियल बाकी है। |
| save-gsoc | clean-16k | 0.000 | 3/3 | याद रखना, जीसॉक अपडेट, लॉगिन फिक्स हो गया, डॉक्स बाकी हैं। |
| save-gsoc | clean-8k | 0.000 | 3/3 | याद रखना, जीसॉक अपडेट, लॉगिन फिक्स हो गया, डॉक्स बाकी हैं। |
| save-gsoc | white-15db | 0.273 | 3/3 | याद रखना, जी सॉक अपडेट, लॉगिन फिक्स हो गया, डॉक्स बाकी है। |
| save-gsoc | white-5db | 0.273 | 3/3 | याद रखना, जी सॉक अपडेट लॉगिन फिक्स हो गया, डॉक्स बाकी है। |
| save-gsoc | rumble-5db | 0.273 | 3/3 | याद रखना, जी सॉक अपडेट, लॉगिन फिक्स हो गया, डॉक्स बाकी है। |
| save-gsoc | babble-5db | 0.909 | 1/3 | याद याद याद याद जी लॉगिन |
| save-gsoc | white-5db-8k | 0.273 | 3/3 | याद रखना, जी सॉक अपडेट, लॉगिन फिक्स हो गया, डॉक्स बाकी है। |
| recall-left | clean-16k | 0.000 | 2/2 | गणित में क्या बचा है |
| recall-left | clean-8k | 0.000 | 2/2 | गणित में क्या बचा है |
| recall-left | white-15db | 0.000 | 2/2 | गणित में क्या बचा है |
| recall-left | white-5db | 0.000 | 2/2 | गणित में क्या बचा है |
| recall-left | rumble-5db | 0.000 | 2/2 | गणित में क्या बचा है |
| recall-left | babble-5db | 0.400 | 1/2 | गणित में क्या |
| recall-left | white-5db-8k | 0.000 | 2/2 | गणित में क्या बचा है |
| remind | clean-16k | 0.143 | 3/3 | कल सुबह 09:00 बजे चाय याद दिलाना। |
| remind | clean-8k | 0.143 | 3/3 | कल सुबह 09:00 बजे चाय याद दिलाना। |
| remind | white-15db | 0.286 | 3/3 | कल सुबह 09:00 बजे चाय याद दिलाना |
| remind | white-5db | 0.286 | 3/3 | कल सुबह 09:00 बजे चाय याद दिलाना |
| remind | rumble-5db | 0.286 | 3/3 | कल सुबह 09:00 बजे चाय याद दिलाना |
| remind | babble-5db | 0.286 | 3/3 | कल सुबह 09:00 बजे चाय याद आती |
| remind | white-5db-8k | 0.286 | 3/3 | कल सुबह 09:00 बजे चाय याद दिलाएं |
| quiz-maths | clean-16k | 0.250 | 1/2 | गणित में क्विज करो। |
| quiz-maths | clean-8k | 0.250 | 1/2 | गणित में क्विज करो। |
| quiz-maths | white-15db | 0.500 | 1/2 | गणित में क्विज करो |
| quiz-maths | white-5db | 0.500 | 1/2 | गणित में क्लिक करो |
| quiz-maths | rumble-5db | 0.250 | 1/2 | गणित में क्विज करो। |
| quiz-maths | babble-5db | 0.750 | 1/2 | गणित करो |
| quiz-maths | white-5db-8k | 0.500 | 1/2 | गणित में क्लिक करो |
