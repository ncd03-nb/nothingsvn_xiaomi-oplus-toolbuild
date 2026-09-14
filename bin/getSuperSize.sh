#!/bin/bash
device_code=$1
case $device_code in
	#13 13Pro 13Ultra K60Pro MIXFold 12TB 14Ultra
	fuxi | nuwa | ishtar | socrates | babylon | marble | aurora | dew | garnet | vermeer | aristotle | corot | degas | duchamp | erhu | goku | guitar | malachite | rothko | ruyi | spring | tornado | yuechu) size=9663676416;;
	#Xiaomi 15 Pro/Ultra Redmi Turbo 4 Pro
	haotian | xuanyuan | onyx | miro | klimt | dada | yudi | rodin | zorn | sheng | luming | bixi | charoite | dali | goya | iolite | jinghu | kunzite | koto | lapis | spinel | taiko | turner) size=11811160064;;
	#Xiaomi Mix Fold 4
	myron | byron) size=14495514624;;
	#Xiaomi 17 Series
	annibale | pudding | popsicle | pandora | prague | chagall | warhol | warsaw | yili) size=13421772800;;
	#Xiaomi 17 Ultra
	nezha) size=15300820992;;
	#Redmi Note 12 5G
	sunstone) size=9122611200;;
	#Xiaomi 14 , 14 Pro
	houji | shennong | shennong_t) size=8321499136;;
	#Redmi 12R
	sky | xun) size=6979321856;;
	#Redmi Note 12/13 13C
	tapas | topaz | sapphire | sapphiren | gale | air | emerald_r | sea) size=7516192768;;
	#Redmi 12C
	earth | breeze) size=7514095616;;
	#Redmi Note 14 4G
	tanzanite | obsidian) size=8053063680;;
	#Redmi Note 13 Pro 4G
	emerald) size=7505707008;;
	#Others
	arctic | mist | somalia) size=10200547328;;
	cupid | diting | ingres | konghou | lake | liuqin | mayfly | mondrian | thor | unicorn | zeus | ziyi | zizhan) size=8589934592;;
	dash | klee) size=12884901888;;
	dijun | muyu | uke) size=11274289152;;
	flame) size=7650410496;;
	flourite | violin) size=10737418240;;
	flute | organ) size=12348030976;;
	moon) size=7247757312;;
	piano | yupei) size=13958643712;;
	serenity) size=5368709120;;
	veux) size=8992587776;;
	athens) size=16106127360;;
	songyuan) size=16642998272;;
	*) size=9126805504;;
esac
echo $size

#pipa 9126805504 |Pad6
#liuqin 9126805504 |Pad6Pro
#sunstone 9126805504 or 9122611200 |Note 12 5G
#rembrandt 9126805504 |K60E
#redwood 9126805504 |Note12ProSpeed
#mondrian 9126805504 |K60
#yunluo 9126805504 |RedmiPad
#ruby 9126805504 |Note 12 Pro
